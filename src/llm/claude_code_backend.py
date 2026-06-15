import asyncio
import shutil
import subprocess
import tempfile
from typing import Any, List, Optional

from .base import LLMBackend, LLMBackendError, Messages

# Tools disabled so the headless `claude` invocation behaves as a pure text
# completion engine and never tries to read/write files or hit the network.
_DISALLOWED_TOOLS = "Bash Edit Write Read WebFetch WebSearch Glob Grep Task NotebookEdit"


class ClaudeCodeBackend(LLMBackend):
    """Translate via the local ``claude`` CLI in headless (``-p``) mode.

    Reuses the user's existing Claude Code login (OAuth) — no API key required.
    The system message is passed via ``--system-prompt`` and the user content via
    stdin (avoids argument-length / escaping issues). The subprocess runs in a
    temp directory so it does not auto-discover the repository ``CLAUDE.md``.

    Generation params such as ``temperature`` / ``max_*`` are ignored: the
    ``claude`` CLI does not expose them.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        max_concurrency: int = 4,
        timeout: int = 600,
        claude_bin: Optional[str] = None,
        effort: Optional[str] = None,
    ):
        self.model = model or None
        self.effort = effort or None  # claude --effort: low/medium/high/xhigh/max
        self.max_concurrency = max_concurrency
        self.timeout = timeout
        self.claude_bin = claude_bin or shutil.which("claude") or "claude"
        self.cwd = tempfile.gettempdir()

    def _build_cmd(self, system_text: str) -> List[str]:
        cmd = [
            self.claude_bin,
            "-p",
            "--output-format",
            "text",
            "--disallowedTools",
            _DISALLOWED_TOOLS,
        ]
        if system_text:
            cmd += ["--system-prompt", system_text]
        if self.model:
            cmd += ["--model", self.model]
        if self.effort:
            cmd += ["--effort", self.effort]
        return cmd

    async def acomplete(
        self,
        messages: Messages,
        *,
        session: Optional[Any] = None,
        **params: Any,
    ) -> str:
        system_text, user_text = self.split_messages(messages)
        cmd = self._build_cmd(system_text)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=user_text.encode("utf-8")), timeout=self.timeout
            )
        except asyncio.TimeoutError as e:
            try:
                proc.kill()
            except Exception:
                pass
            raise LLMBackendError(f"claude CLI timed out after {self.timeout}s") from e
        except (OSError, ValueError) as e:
            raise LLMBackendError(f"failed to launch claude CLI: {e}") from e

        return self._handle_result(proc.returncode, stdout, stderr)

    def complete(self, messages: Messages, **params: Any) -> str:
        system_text, user_text = self.split_messages(messages)
        cmd = self._build_cmd(system_text)
        try:
            proc = subprocess.run(
                cmd,
                input=user_text.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise LLMBackendError(f"claude CLI timed out after {self.timeout}s") from e
        except (OSError, ValueError) as e:
            raise LLMBackendError(f"failed to launch claude CLI: {e}") from e

        return self._handle_result(proc.returncode, proc.stdout, proc.stderr)

    @staticmethod
    def _handle_result(returncode: int, stdout: bytes, stderr: bytes) -> str:
        if returncode != 0:
            err = (stderr or b"").decode("utf-8", errors="replace").strip()
            raise LLMBackendError(f"claude CLI exited with {returncode}: {err}")
        text = (stdout or b"").decode("utf-8", errors="replace").strip()
        if not text:
            raise LLMBackendError("claude CLI returned empty output")
        return text
