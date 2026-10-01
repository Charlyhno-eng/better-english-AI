"""Centralized asynchronous Z.AI chat-completion transport."""
import asyncio
import json
from collections.abc import Sequence

import httpx

from app.ai.contracts import Message
from pydantic import SecretStr

from app.core.config import GLMSettings
from app.core.errors import InvalidTextError, ProviderUnavailableError


class GLMProvider:
    def __init__(self, settings: GLMSettings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings = settings.model_copy(deep=True)
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def set_api_key(self, key: SecretStr) -> None:
        self._settings.api_key = key

    async def complete(self, messages: Sequence[Message]) -> str:
        key = self._settings.api_key
        if key is None or not key.get_secret_value().strip():
            raise ProviderUnavailableError("GLM API key is missing. Add it on the Setup page.")
        if (
            not messages or not any(message.role == "user" for message in messages)
            or any(message.role not in {"system", "user", "assistant"} or not message.content.strip()
                   for message in messages)
            or sum(len(message.content) for message in messages) > self._settings.max_input_characters
        ):
            raise InvalidTextError("The GLM messages are empty, invalid or exceed the input limit.")
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._settings.timeout_seconds, transport=self._transport,
                follow_redirects=False,
            )
        payload = {
            "model": self._settings.model,
            "messages": [{"role": message.role, "content": message.content} for message in messages],
            "max_tokens": self._settings.max_response_tokens,
            "reasoning_effort": self._settings.reasoning_effort,
            "stream": False,
        }
        try:
            # The outer timeout bounds the whole request, not just individual socket reads.
            async with asyncio.timeout(self._settings.timeout_seconds):
                async with self._client.stream(
                    "POST", str(self._settings.api_url), json=payload,
                    headers={"Authorization": f"Bearer {key.get_secret_value()}",
                             "Content-Type": "application/json"},
                ) as response:
                    if response.status_code in {401, 403}:
                        raise ProviderUnavailableError("GLM authentication failed. Check the API key and access.")
                    if response.status_code == 429:
                        raise ProviderUnavailableError("GLM request limit reached. Try again later.")
                    if response.status_code != 200:
                        raise ProviderUnavailableError("GLM API could not complete the request.")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 2 * 1024 * 1024:
                            raise ProviderUnavailableError("GLM returned an oversized response.")
            result = json.loads(body)
            choice = result["choices"][0]
            answer = choice["message"]["content"]
            if not isinstance(answer, str) or not answer.strip() or choice.get("finish_reason") != "stop":
                raise ValueError("Incomplete or invalid completion")
            return answer.strip()
        except ProviderUnavailableError:
            raise
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ProviderUnavailableError("GLM request timed out. Try again later.") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError("Unable to connect to the GLM API.") from exc
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderUnavailableError("GLM returned an invalid or incomplete response.") from exc

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
