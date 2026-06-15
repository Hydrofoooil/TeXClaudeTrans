from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class LLMBackendError(Exception):
    """Raised when a single LLM completion attempt fails.

    Agents catch this in their own retry loops, so a backend performs exactly
    one attempt and raises this on any failure (HTTP error, timeout, non-zero
    subprocess exit, empty output, ...).
    """


Messages = List[Dict[str, str]]


class LLMBackend(ABC):
    """Abstract translation/completion backend.

    A backend turns a list of OpenAI-style chat ``messages`` into a single
    text completion. It performs ONE attempt and raises :class:`LLMBackendError`
    on failure; retry and fail-tracking logic lives in the calling agent.
    """

    #: How many concurrent ``acomplete`` calls the caller should allow.
    max_concurrency: int = 10

    @abstractmethod
    async def acomplete(
        self,
        messages: Messages,
        *,
        session: Optional[Any] = None,
        **params: Any,
    ) -> str:
        """Asynchronously return the completion text for ``messages``.

        ``session`` is an optional shared transport handle (e.g. an
        ``aiohttp.ClientSession``) that backends may ignore. ``params`` are
        backend-specific generation options (``temperature``, ``max_new_tokens``,
        ``max_tokens``, ...); backends ignore options they do not support.
        """
        raise NotImplementedError

    @abstractmethod
    def complete(self, messages: Messages, **params: Any) -> str:
        """Synchronously return the completion text for ``messages``."""
        raise NotImplementedError

    @staticmethod
    def split_messages(messages: Messages) -> (str):
        """Split chat messages into (system_text, user_text).

        Concatenates all ``system`` role contents and all ``user`` role
        contents respectively. Used by backends (e.g. CLI based) that do not
        accept a full message list.
        """
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        user_parts = [m["content"] for m in messages if m.get("role") == "user"]
        return "\n\n".join(system_parts), "\n\n".join(user_parts)
