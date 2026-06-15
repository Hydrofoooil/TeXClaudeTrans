import asyncio
from typing import Any, Optional

import aiohttp
import requests

from .base import LLMBackend, LLMBackendError, Messages


class ApiBackend(LLMBackend):
    """OpenAI-compatible ``/v1/chat/completions`` HTTP backend.

    Reproduces the original request/response handling: the payload is
    ``{"model", "messages", **params}`` (so callers keep passing
    ``temperature`` / ``max_new_tokens`` / ``max_tokens`` exactly as before) and
    the completion is read from ``result["choices"][0]["message"]["content"]``.
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str,
        max_concurrency: int = 10,
        timeout: int = 100,
    ):
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.max_concurrency = max_concurrency
        self.timeout = timeout

    def _payload(self, messages: Messages, params: dict) -> dict:
        return {"model": f"{self.model}", "messages": messages, **params}

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def acomplete(
        self,
        messages: Messages,
        *,
        session: Optional[aiohttp.ClientSession] = None,
        **params: Any,
    ) -> str:
        payload = self._payload(messages, params)
        try:
            if session is not None:
                async with session.post(
                    self.base_url, json=payload, headers=self._headers(), timeout=self.timeout
                ) as response:
                    response.raise_for_status()
                    result = await response.json()
            else:
                async with aiohttp.ClientSession() as own_session:
                    async with own_session.post(
                        self.base_url, json=payload, headers=self._headers(), timeout=self.timeout
                    ) as response:
                        response.raise_for_status()
                        result = await response.json()
            return result["choices"][0]["message"]["content"].strip()
        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError) as e:
            raise LLMBackendError(str(e)) from e

    def complete(self, messages: Messages, **params: Any) -> str:
        payload = self._payload(messages, params)
        try:
            response = requests.post(
                self.base_url, json=payload, headers=self._headers(), timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
        except (requests.exceptions.RequestException, KeyError) as e:
            raise LLMBackendError(str(e)) from e
