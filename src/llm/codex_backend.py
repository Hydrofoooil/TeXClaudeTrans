import asyncio
import os
import shutil
import subprocess
import tempfile
from typing import Any, List, Optional

from .base import LLMBackend, LLMBackendError, Messages


class CodexBackend(LLMBackend):
    """Translate via the local OpenAI ``codex`` CLI (``codex exec``), reusing the
    user's ChatGPT login (no API key needed).

    Verified against codex-cli 0.139.0: the prompt is fed on STDIN, and the
    final answer is read from the file passed to ``-o/--output-last-message``
    (stdout carries a "codex"/"tokens used" banner, so it is NOT parsed). Flags:
    ``--skip-git-repo-check`` (allow a non-git temp cwd), ``--ephemeral`` (no
    session files), ``--color never``, ``-s read-only`` (forbid file edits so it
    behaves as a pure translator). ``codex`` has no system-prompt flag, so the
    system + user messages are merged into one prompt. Runs in a temp cwd so it
    won't read the repo. ``temperature`` etc. are ignored (no CLI equivalent).
    """

    def __init__(
        self,
        model: Optional[str] = None,
        max_concurrency: int = 4,
        timeout: int = 600,
        codex_bin: Optional[str] = None,
        effort: Optional[str] = None,
    ):
        self.model = model or None
        # reasoning effort，经 `-c model_reasoning_effort=<level>` 设置（minimal/low/medium/high）
        self.effort = effort or None
        self.max_concurrency = max_concurrency
        self.timeout = timeout
        self.codex_bin = codex_bin or shutil.which("codex") or "codex"
        self.cwd = tempfile.gettempdir()

    def _build_cmd(self, out_path: str) -> List[str]:
        cmd = [
            self.codex_bin,
            "exec",
            "--skip-git-repo-check",  # 允许在非 git 临时目录运行
            "--ephemeral",            # 不持久化 session 文件
            "--color", "never",
            "--sandbox", "read-only",  # 只读：不让它改文件，当纯翻译器
            "-o", out_path,            # 最终消息写入此文件（= 干净译文）
        ]
        if self.model:
            cmd += ["--model", self.model]
        if self.effort:
            cmd += ["-c", f"model_reasoning_effort={self.effort}"]
        return cmd  # prompt 经 stdin 传入

    @staticmethod
    def _merge(messages: Messages) -> str:
        system_text, user_text = LLMBackend.split_messages(messages)
        return f"{system_text}\n\n{user_text}" if system_text else user_text

    @staticmethod
    def _read_output(out_path: str, returncode, stderr: bytes) -> str:
        text = ""
        try:
            if os.path.exists(out_path):
                with open(out_path, "r", encoding="utf-8") as f:
                    text = f.read().strip()
        finally:
            try:
                os.remove(out_path)
            except OSError:
                pass
        if not text:
            err = (stderr or b"").decode("utf-8", errors="replace").strip()[-500:]
            raise LLMBackendError(f"codex CLI produced no output (rc={returncode}): {err}")
        return text

    async def acomplete(
        self,
        messages: Messages,
        *,
        session: Optional[Any] = None,
        **params: Any,
    ) -> str:
        prompt = self._merge(messages)
        fd, out_path = tempfile.mkstemp(prefix="codex_out_", suffix=".txt")
        os.close(fd)
        cmd = self._build_cmd(out_path)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")), timeout=self.timeout
            )
        except asyncio.TimeoutError as e:
            try:
                proc.kill()
            except Exception:
                pass
            self._cleanup(out_path)
            raise LLMBackendError(f"codex CLI timed out after {self.timeout}s") from e
        except (OSError, ValueError) as e:
            self._cleanup(out_path)
            raise LLMBackendError(f"failed to launch codex CLI: {e}") from e

        return self._read_output(out_path, proc.returncode, stderr)

    def complete(self, messages: Messages, **params: Any) -> str:
        prompt = self._merge(messages)
        fd, out_path = tempfile.mkstemp(prefix="codex_out_", suffix=".txt")
        os.close(fd)
        cmd = self._build_cmd(out_path)
        try:
            proc = subprocess.run(
                cmd,
                input=prompt.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as e:
            self._cleanup(out_path)
            raise LLMBackendError(f"codex CLI timed out after {self.timeout}s") from e
        except (OSError, ValueError) as e:
            self._cleanup(out_path)
            raise LLMBackendError(f"failed to launch codex CLI: {e}") from e

        return self._read_output(out_path, proc.returncode, proc.stderr)

    @staticmethod
    def _cleanup(out_path: str) -> None:
        try:
            os.remove(out_path)
        except OSError:
            pass
