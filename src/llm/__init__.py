from typing import Any, Dict

from .api_backend import ApiBackend
from .base import LLMBackend, LLMBackendError
from .claude_code_backend import ClaudeCodeBackend

__all__ = ["LLMBackend", "LLMBackendError", "ApiBackend", "ClaudeCodeBackend", "create_backend"]


def create_backend(config: Dict[str, Any]) -> LLMBackend:
    """Build the translation backend from ``config``.

    Selected by ``config["llm_config"]["backend"]``:
      - ``"api"`` (default): OpenAI-compatible HTTP endpoint (``ApiBackend``).
      - ``"claude_code"``: local ``claude`` CLI in headless mode
        (``ClaudeCodeBackend``); ``model`` is interpreted as a claude alias
        (e.g. ``opus`` / ``sonnet``), empty means the CLI default.

    Optional ``concurrency`` overrides the per-backend default fan-out.
    """
    llm_cfg = config.get("llm_config", {})
    backend = (llm_cfg.get("backend") or "api").strip().lower()

    if backend == "claude_code":
        kwargs: Dict[str, Any] = {}
        if llm_cfg.get("model"):
            kwargs["model"] = llm_cfg["model"]
        if llm_cfg.get("effort"):
            kwargs["effort"] = llm_cfg["effort"]
        if llm_cfg.get("concurrency"):
            kwargs["max_concurrency"] = int(llm_cfg["concurrency"])
        return ClaudeCodeBackend(**kwargs)

    kwargs = {
        "model": llm_cfg.get("model", "gpt-4o"),
        "base_url": llm_cfg.get("base_url", None),
        "api_key": llm_cfg.get("api_key", None),
    }
    if llm_cfg.get("concurrency"):
        kwargs["max_concurrency"] = int(llm_cfg["concurrency"])
    return ApiBackend(**kwargs)
