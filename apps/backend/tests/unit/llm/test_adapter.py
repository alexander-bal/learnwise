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
