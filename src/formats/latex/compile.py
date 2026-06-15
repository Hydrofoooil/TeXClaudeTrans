from typing import List, Dict, Any
import re
import os
import signal
import subprocess
from .utils import *

# 非英文目标通常需要 Unicode 引擎(xelatex)；英文用 pdflatex 更快。
_LATIN_LANGS = {"", "en", "english"}


class LaTexCompiler:
    def __init__(self, output_latex_dir: str, target_language: str = None):
        self.output_latex_dir = output_latex_dir
        self.target_language = (target_language or "").strip().lower()

    def _run_latexmk(self, tex_file: str, out_dir: str, engine: str, timeout: int = 600) -> bool:
        """用 latexmk 跑一个引擎，带超时 + 进程组清理，避免卡死
        （例如 pdflatex 编译中文时的宏死循环）。返回 latexmk 是否正常退出（returncode==0）。"""
        # 统一用绝对路径：latexmk 的 cwd 是 tex 所在目录，-outdir 用相对路径会错位。
        out_dir = os.path.abspath(out_dir)
        tex_file = os.path.abspath(tex_file)
        os.makedirs(out_dir, exist_ok=True)
        cmd = [
            "latexmk",
            f"-{engine}",
            "-interaction=nonstopmode",
            f"-outdir={out_dir}",
            "-file-line-error",
            "-synctex=1",
            "-f",
        ]
        if engine in ("xelatex", "lualatex"):
            # 有些文档假设用 pdflatex（如 \input glyphtounicode 会调用 \pdfglyphtounicode）。
            # 这些 pdftex 专有命令在 xelatex 下未定义会报错；用 pretex 注入 no-op 垫片跳过它们。
            cmd.append(r"-usepretex=\providecommand\pdfglyphtounicode[2]{}")
        cmd.append(tex_file)
        cwd = os.path.dirname(tex_file)
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=cwd, start_new_session=True,
            )
        except OSError as e:
            print(f"⚠️  Failed to launch latexmk ({engine}): {e}")
            return False
        try:
            proc.communicate(timeout=timeout)
            return proc.returncode == 0
        except subprocess.TimeoutExpired:
            # 杀掉整个进程组（latexmk 及其 latex 子进程），防止残留空转
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait()
            print(f"⚠️  {engine} timed out after {timeout}s — aborted (likely a macro loop or missing font).")
            return False

    def compile(self):
        """编译 LaTeX 文档。英文目标用 pdflatex（快）、失败回退 xelatex；
        中文等非拉丁语言直接用 xelatex（pdflatex 编不了 CJK，还可能宏死循环）。"""
        tex_file_to_compile = find_main_tex_file(self.output_latex_dir)
        if not tex_file_to_compile:
            print("⚠️ Warning: There is no main tex file to compile in this directory.")
            return None

        if self.target_language in _LATIN_LANGS:
            engines = ["pdflatex", "xelatex"]
        else:
            engines = ["xelatex"]

        for engine in engines:
            print(f"Start compiling with {engine}...⏳")
            out_dir = os.path.join(self.output_latex_dir, f"build_{engine}")
            self._run_latexmk(tex_file_to_compile, out_dir, engine)
            pdf_files = [os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.lower().endswith(".pdf")]
            if pdf_files:
                print("✅  Successfully generated PDF file !")
                return pdf_files[0]
            print(f"⚠️  Failed to generate PDF with {engine}.")

        print("⚠️  Failed to generate PDF. Check the logs under the build_* directories.")
        return None
    

    def compile_ja(self):
        """
        Compile the LaTeX document .
        """
        tex_file_to_compile = find_main_tex_file(self.output_latex_dir)
        if not tex_file_to_compile:
            print("⚠️ Warning: There is no main tex file to compile in this directory.")
            return None
        print("Start compiling with lualatex...⏳")
        compile_out_dir_lualatex = os.path.join(self.output_latex_dir, "build_lualatex")
        self._compile_with_lualatex(tex_file_to_compile, compile_out_dir_lualatex, engine="lualatex")
        pdf_files = [os.path.join(compile_out_dir_lualatex, file) for file in os.listdir(compile_out_dir_lualatex) if file.lower().endswith('.pdf')]
        if pdf_files:

            print(f"✅  Successfully generated PDF file !") 
            return pdf_files[0]
        else:
            print(f"⚠️  Failed to generate PDF with xelatex. Please check the log.")
            # log_files_xelatex = [os.path.join(compile_out_dir_xelatex, file) for file in os.listdir(compile_out_dir_xelatex) if file.lower().endswith('.log')]
            log_files_lualatex = [os.path.join(compile_out_dir_lualatex, file) for file in os.listdir(compile_out_dir_lualatex) if file.lower().endswith('.log')]
            if log_files_lualatex:
                print(f"📄 Log files for pdflatex: {log_files_lualatex}")
            return None

    def compile_source(self, pdf_dir):
        if pdf_dir is None:
            pdf_dir = self.output_latex_dir
        os.makedirs(pdf_dir, exist_ok=True)  # Ensure directory exists

        tex_file_to_compile = find_main_tex_file(self.output_latex_dir)
        if not tex_file_to_compile:
            print("⚠️ Warning: No main .tex file found in directory.")
            return None

        print("Start compiling with pdflatex...⏳")
        self._compile_with_pdflatex(
            tex_file_to_compile,
            out_dir=pdf_dir,  # Output directly to pdf_dir
            engine="pdflatex"
        )

        pdf_files = [
            f for f in os.listdir(pdf_dir)
            if f.lower().endswith('.pdf') and not f.startswith('._')  # Skip macOS temp files
        ]

        if pdf_files:
            pdf_path = os.path.join(pdf_dir, pdf_files[0])
            print(f"✅ Successfully generated PDF at: {pdf_path}")
            return pdf_path

        # Fallback to xelatex if pdflatex failed
        print("⚠️ pdflatex failed. Retrying with xelatex...⏳")
        self._compile_with_xelatex(
            tex_file_to_compile,
            out_dir=pdf_dir,  # Output directly to pdf_dir
            engine="xelatex"
        )

        pdf_files = [
            f for f in os.listdir(pdf_dir)
            if f.lower().endswith('.pdf') and not f.startswith('._')
        ]

        if pdf_files:
            pdf_path = os.path.join(pdf_dir, pdf_files[0])
            print(f"✅ Successfully generated PDF at: {pdf_path}")
            return pdf_path

        # If both compilers failed
        print("⚠️ Failed to generate PDF with both compilers.")
        log_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith('.log')]
        if log_files:
            print("📄 Compilation logs:")
            for log in log_files:
                print(f"  - {os.path.join(pdf_dir, log)}")

        return None

    def _compile_with_pdflatex(self, tex_file: str, out_dir: str, engine: str = "pdflatex"):
        self._run_latexmk(tex_file, out_dir, engine)

    def _compile_with_xelatex(self, tex_file: str, out_dir: str, engine: str = "xelatex"):
        self._run_latexmk(tex_file, out_dir, engine)

    def _compile_with_lualatex(self, tex_file: str, out_dir: str, engine: str = "lualatex"):
        self._run_latexmk(tex_file, out_dir, engine)
