import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from app.llm.adapter import AdapterResult, ModelSettings, OllamaAdapter, parse_retry_after
from app.llm.errors import (
    LlmFailure,
    OutputInvalid,
    ProviderMisconfigured,
    ProviderRejected,
    ProviderUnavailable,
)
from app.llm.schemas import TriageRecord

SETTINGS = ModelSettings(num_ctx=8192, num_predict=256, seed=42)


def answer(content: str, *, done_reason: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "message": {"role": "assistant", "content": content},
            "done": True,
            "done_reason": done_reason,
            "prompt_eval_count": 12,
            "eval_count": 7,
        },
    )


async def call(response: httpx.Response | Exception) -> tuple[AdapterResult, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if isinstance(response, Exception):
            raise response
        return response

    adapter = OllamaAdapter("http://model", transport=httpx.MockTransport(handler))
    try:
        result = await adapter.chat(
            model="m",
            prompt="PROMPT",
            content="MESSAGE",
            output_schema=TriageRecord,
            settings=SETTINGS,
        )
    finally:
        await adapter.aclose()
    return result, seen


async def test_a_valid_answer_is_a_record_with_tokens_and_the_request_is_constrained() -> None:
    result, [request] = await call(answer('{"intent": "billing", "urgency": "low"}'))

    assert result.output == TriageRecord(intent="billing", urgency="low")
    assert (result.input_tokens, result.output_tokens) == (12, 7)
    body = json.loads(request.content)
    assert body["messages"] == [
        {"role": "system", "content": "PROMPT"},
        {"role": "user", "content": "MESSAGE"},
    ]
    assert body["format"] == TriageRecord.model_json_schema()
    assert body["think"] is False and body["stream"] is False
    assert body["options"] == {"temperature": 0.0, "seed": 42, "num_predict": 256, "num_ctx": 8192}


@pytest.mark.parametrize(
    ("response", "failure"),
    [
        (httpx.Response(500), ProviderUnavailable),
        (httpx.Response(503), ProviderUnavailable),
        (httpx.Response(429), ProviderUnavailable),
        (httpx.ConnectError("refused"), ProviderUnavailable),
        (httpx.Response(404), ProviderMisconfigured),
        (httpx.Response(400), ProviderRejected),
        (httpx.Response(413), ProviderRejected),
        (answer("not json"), OutputInvalid),
        (answer('{"intent": "billing"}'), OutputInvalid),
        (answer('{"intent": "billing", "urgency": "low", "extra": 1}'), OutputInvalid),
        (answer('{"intent": "refund", "urgency": "low"}'), OutputInvalid),
        (answer('{"intent": "billing", "urgency": "low"}', done_reason="length"), OutputInvalid),
        (httpx.Response(200, text="<html>"), OutputInvalid),
        (httpx.Response(200, json=["not", "an", "object"]), OutputInvalid),
        (httpx.Response(200, json={"done": True}), OutputInvalid),
        (httpx.Response(200, json={"message": {"content": None}}), OutputInvalid),
        (httpx.Response(200, json={"message": {"content": 5}}), OutputInvalid),
        (httpx.Response(200, json={"message": "no content key"}), OutputInvalid),
    ],
)
async def test_failures_are_classified(
    response: httpx.Response | Exception, failure: type[LlmFailure]
) -> None:
    with pytest.raises(LlmFailure) as exc:
        await call(response)
    assert type(exc.value) is failure


async def test_a_429_carries_the_servers_retry_after() -> None:
    with pytest.raises(ProviderUnavailable) as exc:
        await call(httpx.Response(429, headers={"Retry-After": "12"}))
    assert exc.value.retry_after == 12


def test_retry_after_is_read_as_seconds_or_an_http_date() -> None:
    assert parse_retry_after("3") == 3
    assert parse_retry_after(None) is None
    assert parse_retry_after("soon") is None
    later = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    assert 28 <= (parse_retry_after(later) or 0) <= 30


def test_a_retry_after_in_the_past_or_negative_is_zero_not_negative() -> None:
    assert parse_retry_after("-5") == 0
    earlier = format_datetime(datetime.now(UTC) - timedelta(seconds=30), usegmt=True)
    assert parse_retry_after(earlier) == 0


async def test_keep_alive_is_sent_only_when_the_settings_ask_for_it() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answer('{"intent": "billing", "urgency": "low"}')

    adapter = OllamaAdapter("http://model", transport=httpx.MockTransport(handler))
    try:
        for keep_alive in (None, -1):
            await adapter.chat(
                model="m",
                prompt="P",
                content="C",
                output_schema=TriageRecord,
                settings=ModelSettings(
                    num_ctx=8192, num_predict=256, seed=42, keep_alive=keep_alive
                ),
            )
    finally:
        await adapter.aclose()

    assert "keep_alive" not in json.loads(seen[0].content)
    assert json.loads(seen[1].content)["keep_alive"] == -1


async def test_warm_up_loads_the_model_with_the_context_window_calls_use() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"done": True})

    adapter = OllamaAdapter("http://model", transport=httpx.MockTransport(handler))
    try:
        await adapter.warm_up("m", 8192)
    finally:
        await adapter.aclose()

    assert seen[0].url.path == "/api/generate"
    assert json.loads(seen[0].content) == {
        "model": "m",
        "keep_alive": -1,
        "options": {"num_ctx": 8192},
    }
