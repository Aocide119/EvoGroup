"""Injectable model interface and a synchronous Chat Completions transport."""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

import httpx
from pydantic import Field

from evog.config import Settings
from evog.errors import ProviderError
from evog.models import Record


class ToolCall(Record):
    id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any]


class ModelReply(Record):
    content: str = Field(default="", max_length=256000)
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=16)
    usage: dict[str, int] = Field(default_factory=dict)


class Provider(Protocol):
    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply: ...


class ChatProvider:
    """Provider keys are never written to traces. Inject an httpx client in tests."""

    def __init__(self, settings: Settings, *, client: httpx.Client | None = None):
        if not settings.base_url or not settings.model or not settings.api_key.get_secret_value():
            raise ProviderError("Set EVOG_BASE_URL, EVOG_MODEL and EVOG_API_KEY for live requests")
        try:
            parsed = httpx.URL(settings.base_url)
        except httpx.InvalidURL as exc:
            raise ProviderError("Invalid provider API root") from exc
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.host
            or parsed.userinfo
            or parsed.query
            or parsed.fragment
        ):
            raise ProviderError("Base URL must be an HTTP(S) API root without credentials or query")
        self.settings = settings
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=settings.request_timeout)

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelReply:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "max_tokens": self.settings.max_output_tokens,
        }
        if tools:
            payload["tools"] = tools
        for attempt in range(3):
            try:
                response = self.client.post(
                    self.settings.base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {self.settings.api_key.get_secret_value()}"},
                    json=payload,
                    timeout=self.settings.request_timeout,
                )
            except httpx.HTTPError as exc:
                raise ProviderError("Provider transport failed") from exc
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(0.5 * (2**attempt))
                continue
            if response.is_error:
                raise ProviderError(f"Provider request failed (HTTP {response.status_code})")
            try:
                data = response.json()
                raw = data["choices"][0]["message"]
                calls = [
                    ToolCall(
                        id=call["id"],
                        name=call["function"]["name"],
                        arguments=json.loads(call["function"]["arguments"]),
                    )
                    for call in raw.get("tool_calls", [])
                ]
                if len({call.id for call in calls}) != len(calls) or len(calls) > 16:
                    raise ValueError("Invalid tool call IDs or oversized call batch")
                usage = {
                    key: int(value)
                    for key, value in (data.get("usage") or {}).items()
                    if key in ("prompt_tokens", "completion_tokens", "total_tokens")
                }
                return ModelReply(content=raw.get("content") or "", tool_calls=calls, usage=usage)
            except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
                raise ProviderError("Provider returned an invalid chat response") from exc
        raise ProviderError("Provider retry budget exhausted")

    def close(self) -> None:
        if self._owns_client:
            self.client.close()


def assistant_message(reply: ModelReply) -> dict[str, Any]:
    result: dict[str, Any] = {"role": "assistant", "content": reply.content or None}
    if reply.tool_calls:
        result["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in reply.tool_calls
        ]
    return result
