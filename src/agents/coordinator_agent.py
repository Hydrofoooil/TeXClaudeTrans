import os
import re
import json
import shutil
from typing import Any, Dict, List, Optional
from pathlib import Path
import sys
import asyncio

base_dir = os.getcwd()
sys.path.append(base_dir)

from .tool_agents.base_tool_agent import BaseToolAgent
from .tool_agents.parser_agent import ParserAgent
from .tool_agents.translator_agent import TranslatorAgent 
from .tool_agents.generator_agent import GeneratorAgent
from .tool_agents.validator_agent import ValidatorAgent
import gc


def _load_simple_newcommands(newcommands_path: str) -> dict:
    """从 newcommands_map 解析无参、无 # 的简单命令 -> {'\\name': 'value'}，
    用于展开标题里论文自定义的简称命令(如 \\evalname -> WorldModelBench)。"""
    cmds = {}
    try:
        with open(newcommands_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return cmds
    for item in data:
        content = item.get("content", "") or ""
        m = re.match(r"\s*\\(?:re)?newcommand\*?\s*\{\s*\\([a-zA-Z]+)\s*\}\s*\{(.*)\}\s*$", content, re.DOTALL)
        if m and "#" not in m.group(2):
            cmds["\\" + m.group(1)] = m.group(2).strip()
    return cmds


def _extract_title_for_filename(captions_path: str, fallback_tex_dir: str = None,
                                use_translation: bool = False, maxlen: int = 120):
    """提取论文标题并清理成合法文件名。不同会议模板的标题命令不同
    (\\title / \\icmltitle / \\maintitle 等),所以匹配任何含 'title' 的 cap_type
    (排除 running/short 这类页眉短标题);captions 取不到时回退到重建主 tex 里 grep。
    use_translation=False 取原文(英文)标题。失败返回 None。"""
    raw = None
    # 1) 从 captions_map 找标题类条目(优先 title,其次 icmltitle,再任意 *title)
    try:
        with open(captions_path, "r", encoding="utf-8") as f:
            caps = json.load(f)
        candidates = {}
        for c in caps:
            ct = (c.get("cap_type") or "").lower()
            if "title" in ct and "running" not in ct and "short" not in ct:
                candidates.setdefault(ct, c)
        chosen = None
        for pref in ("title", "icmltitle", "maintitle"):
            if pref in candidates:
                chosen = candidates[pref]
                break
        if not chosen and candidates:
            chosen = next(iter(candidates.values()))
        if chosen:
            raw = chosen.get("trans_content" if use_translation else "content") or chosen.get("content") or ""
    except Exception:
        pass
    # 2) 回退:从重建主 tex grep 标题命令(防 parser 未提取成 caption 的模板)
    if not raw and fallback_tex_dir:
        try:
            from src.formats.latex.utils import find_main_tex_file
            mt = find_main_tex_file(fallback_tex_dir)
            if mt:
                with open(mt, "r", encoding="utf-8") as f:
                    tex = f.read()
                mm = re.search(r"\\[a-zA-Z@]*title\*?\s*(?:\[[^\]]*\])?\s*\{", tex)
                if mm:
                    raw = tex[mm.start():mm.start() + 600]  # 截一段供下方正则提取
        except Exception:
            pass
    if not raw:
        return None
    # 从 \...title{...} 提取标题文本(匹配 \title / \icmltitle 等)
    m = re.search(r"\\[a-zA-Z@]*title\*?\s*(?:\[[^\]]*\])?\s*\{(.+)\}", raw, re.DOTALL)
    text = m.group(1) if m else raw
    # 展开论文自定义的无参简称命令(如 \evalname -> WorldModelBench)，否则会被当普通命令删掉
    cmds = _load_simple_newcommands(os.path.join(os.path.dirname(captions_path), "newcommands_map.json"))
    for _ in range(3):  # 多遍以处理嵌套
        prev = text
        for name, val in cmds.items():
            text = re.sub(re.escape(name) + r"(?![a-zA-Z])", lambda _m, v=val: v, text)
        if text == prev:
            break
    text = text.replace("~", " ")                            # 不换行空格 -> 空格
    text = re.sub(r"\\thanks\s*\{[^{}]*\}", "", text)         # 去脚注
    text = re.sub(r"\\[a-zA-Z]+\*?\s*\{([^{}]*)\}", r"\1", text)  # \cmd{x} -> x
    text = re.sub(r"\\[a-zA-Z]+\*?", "", text)                # 剩余 \cmd
    text = text.replace("{", "").replace("}", "")
    text = re.sub(r'[\\/:*?"<>|\n\r\t]', " ", text)           # 非法文件名字符
    text = re.sub(r"\s+", " ", text).strip()
    text = text[:maxlen].strip()
    return text or None


class CoordinatorAgent:
    """
    The main orchestrator agent for the translation system.
    It coordinates the workflow of various tool agents based on document format
    and configuration.
    """

    def __init__(self, 
                 config: Dict[str, Any],
                 project_dir: str = None,
                 output_dir: Optional[str] = None
                 ):
        """
        Initializes the CoordinatorAgent.
        """
        self.config = config
        self.name = config.get("sys_name", "LaTeXTrans")
        self.target_language = config.get("target_language", "ch")
        self.source_language = config.get("source_language", "en")
        self.project_dir = project_dir  # Project path for parsing
        self.output_dir = output_dir  # Output directory for parsed files
        self.loop = asyncio.new_event_loop()
        self.mode = config.get("mode", 0)

    def run_async(self, coro):
        """
        Run asynchronous coroutines in the existing event loop
        """
        return self.loop.run_until_complete(coro)

    async def workflow_latextrans_async(self) -> None:
        """
        initializes the tool agent based on the provided agent name key.
        """
        base_name = os.path.basename(self.project_dir)
        transed_project_dir = os.path.join(self.output_dir, f"{self.target_language}_{base_name}")

        os.makedirs(transed_project_dir, exist_ok=True)

        parser_agent = ParserAgent(config=self.config,
                                   project_dir=self.project_dir,
                                   output_dir=transed_project_dir)
        parser_agent.execute()  

        translator_agent = TranslatorAgent(config=self.config,
                                           project_dir=self.project_dir,
                                           output_dir=transed_project_dir,
                                           trans_mode=self.mode)
        await translator_agent.execute()  # await
        validator_agent = ValidatorAgent(config=self.config,
                                            project_dir=self.project_dir,
                                            output_dir=transed_project_dir)
        errors_report = validator_agent.execute()
        MAX_RETRIES = 3
        retry_count = 0
        if errors_report:
            translator_agent.trans_mode = 1

        while errors_report and retry_count < MAX_RETRIES: # 3 times
            translator_agent.errors_report = errors_report
            await translator_agent.execute(error_retry_count=retry_count, Maxtry=MAX_RETRIES)
            errors_report = validator_agent.execute(errors_report)
            retry_count += 1

        generator_agent = GeneratorAgent(config=self.config,
                                         project_dir=self.project_dir,
                                         output_dir=transed_project_dir)
        try:
        
            PDF_file_path = generator_agent.execute()
        except Exception as e:
            print(f"🤖🚧 {self.name}: Failed to translated {os.path.basename(self.project_dir)}.{e}")
            return
        
        if PDF_file_path:
            new_PDF_path = os.path.join(transed_project_dir, f"{self.target_language}_{base_name}.pdf")
            shutil.move(PDF_file_path, new_PDF_path)
            print(f"🤖🎉 {self.name}: Successfully translated {os.path.basename(self.project_dir)} to {new_PDF_path}.")
            # 额外在 outputs 根目录存一份，以论文英文标题命名，便于查找
            title = _extract_title_for_filename(
                os.path.join(transed_project_dir, "captions_map.json"),
                fallback_tex_dir=os.path.join(transed_project_dir, base_name),
            )
            if title:
                titled_pdf = os.path.join(self.output_dir, f"{title}.pdf")
                try:
                    shutil.copy(new_PDF_path, titled_pdf)
                    print(f"🤖📄 {self.name}: Also saved as {titled_pdf}.")
                except OSError as e:
                    print(f"⚠️ Failed to save titled copy: {e}")
        else:
            print(f"🤖🚧 {self.name}: Failed to translated {os.path.basename(self.project_dir)}.")


    def workflow_latextrans(self) -> None:
        """
        Initialize the tool agent and execute the LaTeX conversion workflow 
        (with event loop security management)
        """

        if hasattr(self, 'loop') and not self.loop.is_closed():
            self.loop.close()  

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            self.loop.run_until_complete(self.workflow_latextrans_async())

        finally:
            # Complete all asynchronous resource recycling
            if tasks := asyncio.all_tasks(self.loop):
                self.loop.run_until_complete(
                    asyncio.gather(*tasks, return_exceptions=True)
                )

            # Special handling of asynchronous I/O recycling in Windows
            if sys.platform == "win32":
                self.loop.run_until_complete(
                    self.loop.shutdown_asyncgens()
                )

            self.loop.run_until_complete(self.loop.shutdown_default_executor())
