from typing import Dict, Any, List
from src.agents.tool_agents.base_tool_agent import BaseToolAgent
from pathlib import Path
import sys
import os
import shutil

from src.utils.progress import st
import time

base_dir = os.getcwd()
sys.path.append(base_dir)

 
class GeneratorAgent(BaseToolAgent):
    def __init__(self, 
                 config: Dict[str, Any],
                 project_dir: str = None,
                 output_dir: str = None  # Output directory for parsed files
                 ):
        super().__init__(agent_name="GeneratorAgent", config=config)
        self.config = config
        self.project_dir = project_dir
        self.output_dir = output_dir  # Output directory for parsed files

    def execute(self) -> Any:
        sys.stderr = open(os.devnull, 'w')
        self.process_b = st.empty()
        with self.process_b:
            self.progress_bar = st.progress(0)
        self.status_text = st.empty()
        sys.stderr = sys.__stderr__
        
        self.log(f"🤖💬 Start generating for project...⏳: {os.path.basename(self.project_dir)}.")

        sys.stderr = open(os.devnull, 'w')
        self.status_text.text("🔄 Start generating for project...")
        self.progress_bar.progress(5)
        sys.stderr = sys.__stderr__

        from src.formats.latex.compile import LaTexCompiler
        from src.formats.latex.reconstruct import LatexConstructor

        sys.stderr = open(os.devnull, 'w')
        self.status_text.text("📂 Reading...")
        self.progress_bar.progress(10)
        sys.stderr = sys.__stderr__
        sections = self.read_file(Path(self.output_dir, "sections_map.json"), "json")
        sys.stderr = open(os.devnull, 'w')
        self.progress_bar.progress(20)
        sys.stderr = sys.__stderr__
        captions = self.read_file(Path(self.output_dir, "captions_map.json"), "json")
        sys.stderr = open(os.devnull, 'w')
        self.progress_bar.progress(30)
        sys.stderr = sys.__stderr__
        envs = self.read_file(Path(self.output_dir, "envs_map.json"), "json")
        sys.stderr = open(os.devnull, 'w')
        self.progress_bar.progress(40)
        sys.stderr = sys.__stderr__
        newcommands = self.read_file(Path(self.output_dir, "newcommands_map.json"), "json")
        sys.stderr = open(os.devnull, 'w')
        self.progress_bar.progress(50)
        sys.stderr = sys.__stderr__
        inputs = self.read_file(Path(self.output_dir, "inputs_map.json"), "json")
        sys.stderr = open(os.devnull, 'w')
        self.progress_bar.progress(60)

        self.status_text.text("📁 Creating translation project directory ..")
        sys.stderr = sys.__stderr__

        transed_latex_dir = self._creat_transed_latex_folder(self.project_dir)

        sys.stderr = open(os.devnull, 'w')
        self.progress_bar.progress(70)
        sys.stderr = sys.__stderr__

        print(transed_latex_dir)

        sys.stderr = open(os.devnull, 'w')
        self.status_text.text("🔨 Refactoring LaTeX document...")
        sys.stderr = sys.__stderr__
        latex_constructor = LatexConstructor(
                                sections=sections,
                                captions=captions,
                                envs=envs,
                                inputs=inputs,
                                newcommands=newcommands,
                                output_latex_dir=transed_latex_dir,
                                cjk_engine=self.config.get("cjk_engine", "xecjk"),
                            )
        latex_constructor.construct()

        self._inject_arxiv_stamp(transed_latex_dir)

        sys.stderr = open(os.devnull, 'w')
        self.progress_bar.progress(80)
        self.status_text.text("🛠️ Compiling PDF document...")
        sys.stderr = sys.__stderr__

        latex_compiler = LaTexCompiler(
            output_latex_dir=transed_latex_dir,
            target_language=self.config.get("target_language", "ch"),
        )
        pdf_file = latex_compiler.compile()

        sys.stderr = open(os.devnull, 'w')
        self.progress_bar.progress(90)
        sys.stderr = sys.__stderr__
        if pdf_file:

            sys.stderr = open(os.devnull, 'w')
            self.status_text.text("✅ Successfully compiled PDF document.")
            self.progress_bar.progress(100)
            st.success(f"✅ Successfully generated for {os.path.basename(self.project_dir)}.")
            time.sleep(2)
            self.process_b.empty()
            self.status_text.empty()
            sys.stderr = sys.__stderr__

            self.log(f"✅ Successfully generated for {os.path.basename(self.project_dir)}.")
            return pdf_file
        else:
            sys.stderr = open(os.devnull, 'w')
            self.status_text.error("❌ Failed to compile PDF document.")
            self.process_b.empty()
            sys.stderr = sys.__stderr__
            return None
        
    def _creat_transed_latex_folder(self, src_dir: str) -> str:
        """
        Create a translated folder by copying the source directory and renaming it.
        """
        if not os.path.isdir(src_dir):
            raise NotADirectoryError(f"The path {src_dir} is not a valid directory.")

        base_name = os.path.basename(src_dir)
        dest_dir = os.path.join(self.output_dir, base_name)

        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir)
        shutil.copytree(src_dir, dest_dir)

        return dest_dir

    def _inject_arxiv_stamp(self, tex_dir: str) -> None:
        """给重建项目的主 tex 注入 arXiv 左侧竖排戳(序号+分类+日期),模拟 arXiv 发布版。
        仅当 config['arxiv_stamp'] 为真(默认 True)、且项目名能识别出 arXiv ID(即来自
        arXiv 翻译)时生效;本地项目无 arXiv 元数据则自动跳过。"""
        if not self.config.get("arxiv_stamp", True):
            return
        import re
        from src.formats.latex.utils import find_main_tex_file

        base = os.path.basename(self.project_dir)
        m = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)", base)  # 从项目名提取 arXiv ID
        if not m:
            return  # 非 arXiv 来源(本地项目),跳过
        arxiv_id = m.group(1)

        cats = (self.config.get("category") or {}).get(arxiv_id) or []
        date = (self.config.get("arxiv_date") or {}).get(arxiv_id)
        parts = [f"arXiv:{arxiv_id}"]
        if cats:
            parts.append(f"[{cats[0]}]")
        if date:
            parts.append(date)
        stamp = "  ".join(parts)

        # 把 \today 固定为 arXiv 提交日期(英文 "February 9, 2026" 形式)，
        # 避免页脚 "Preprint. \today" 显示"今天"或被 ctex 中文化成"年月日"。
        # (注：原作者本地编译日不可知，这里用 arXiv 提交日作为最接近的代替。)
        today_cmd = ""
        if date:
            _mon = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
                    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
            _full = ["January", "February", "March", "April", "May", "June",
                     "July", "August", "September", "October", "November", "December"]
            eng_date = date.strip()
            dp = eng_date.split()
            if len(dp) == 3 and dp[1][:3] in _mon:
                eng_date = "%s %s, %s" % (_full[_mon[dp[1][:3]] - 1], dp[0].lstrip("0"), dp[2])
            today_cmd = r"\renewcommand{\today}{" + eng_date + "}"

        main_tex = find_main_tex_file(tex_dir)
        if not main_tex:
            return
        try:
            with open(main_tex, "r", encoding="utf-8") as f:
                s = f.read()
            # 用 textpos 绝对定位(独立包,不与 cvpr/iccv 自带的 \LenToUnit/\AddToShipoutPicture 冲突)
            if "{textpos}" not in s:
                s = re.sub(r"(\\documentclass[^\n]*\n)", r"\1\\usepackage[absolute,overlay]{textpos}\n", s, count=1)
            # 2.25 倍、灰色 #808080、衬线字体。用文档自带的 roman 字族(\rmfamily),
            # 完全可移植——不依赖任何外部字体文件，任何装了 TeX 的机器都能编译。
            styled = r"\scalebox{2.25}{\textcolor[gray]{0.5}{\rmfamily\small " + stamp + r"}}"
            inject = (
                today_cmd +
                r"\begin{textblock*}{3cm}[0.5,0.5](2.0cm,0.5\paperheight)"
                r"\rotatebox[origin=c]{90}{" + styled + r"}"
                r"\end{textblock*}"
            )
            s = s.replace(r"\begin{document}", r"\begin{document}" + "\n" + inject + "\n", 1)
            with open(main_tex, "w", encoding="utf-8") as f:
                f.write(s)
            self.log(f"🏷️ Injected arXiv stamp: {stamp}")
        except OSError as e:
            print(f"⚠️ Failed to inject arXiv stamp: {e}")
        
    


# import toml
# import argparse

# parser = argparse.ArgumentParser()
# parser.add_argument("--config", type=str, default="config/default.toml")
# args = parser.parse_args()

# config = toml.load(args.config)
# dir = "D:\code\AutoLaTexTrans\output\ch_arXiv-2504.06261v2/arXiv-2504.06261v2"
# Validator = ValidatorAgent(config=config,
#                           project_dir=config["paths"].get("project_dir", None),
#                           validator_dir=dir
#                           )
# Validator.execute()
