import json

import httpx
import pytest

from evog.config import Settings
from evog.errors import ProviderError
from evog.providers import ChatProvider


def settings():
    return Settings(
        base_url="https://provider.example/v1", model="example", api_key="private-token"
    )


def test_provider_encodes_tools_and_parses_response_without_credential_output():
    def respond(request):
        assert str(request.url) == "https://provider.example/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer private-token"
        assert json.loads(request.content)["model"] == "example"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "function": {"name": "list_files", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        provider = ChatProvider(settings(), client=client)
        reply = provider.complete([{"role": "user", "content": "hi"}], [])
        assert reply.tool_calls[0].arguments == {}
        assert reply.usage["prompt_tokens"] == 10
        assert "private-token" not in reply.model_dump_json()
        provider.close()
        assert not client.is_closed


def test_provider_http_error_body_is_not_exposed():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(403, text="private-token secret body")
        )
    ) as client:
        with pytest.raises(ProviderError, match="HTTP 403") as failure:
            ChatProvider(settings(), client=client).complete([], [])
        assert "private-token" not in str(failure.value)


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"choices": []},
        {"choices": [{"message": []}]},
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"id": "1", "function": {"name": "x", "arguments": "not-json"}}
                        ]
                    }
                }
            ]
        },
    ],
)
def test_invalid_provider_response_has_a_safe_error(response):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))
    ) as client:
        with pytest.raises(ProviderError, match="invalid chat response"):
            ChatProvider(settings(), client=client).complete([], [])


def test_retry_is_bounded_and_http_success_is_parsed(monkeypatch):
    monkeypatch.setattr("evog.providers.time.sleep", lambda _: None)
    attempts = []

    def respond(_):
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert ChatProvider(settings(), client=client).complete([], []).content == "{}"
    assert len(attempts) == 3


def test_provider_config_requires_credentials_and_clean_api_root():
    with pytest.raises(ProviderError, match="Set EVOG"):
        ChatProvider(Settings())
    with pytest.raises(ProviderError, match="Base URL"):
        ChatProvider(
            Settings(base_url="https://user:password@example.com/v1", model="x", api_key="x")
        )
