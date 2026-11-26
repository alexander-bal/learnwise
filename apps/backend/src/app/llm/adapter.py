"""The one Ollama adapter, used for both provider profiles (Processing NFR-5).

It makes exactly one HTTP request per call and classifies its outcome; timeouts, retries,
limits and the breaker are the gateway's.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.llm.errors import (
    OutputInvalid,
    ProviderMisconfigured,
    ProviderRejected,
    ProviderUnavailable,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelSettings:
    """The settings every call sets (Processing NFR-5)."""

    num_ctx: int
    num_predict: int
    seed: int
    temperature: float = 0.0
    think: bool = False
    # Ollama unloads a model 5 minutes after a call that sets no keep_alive, so a call on a
    # model to keep warm sets -1. Not a recorded setting: it does not change the output.
    keep_alive: int | None = None

    def as_options(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "seed": self.seed,
            "num_predict": self.num_predict,
            "num_ctx": self.num_ctx,
        }

    def as_config(self) -> dict[str, Any]:
        return {"think": self.think, **self.as_options()}


@dataclass(frozen=True)
class AdapterResult:
    output: BaseModel
    input_tokens: int | None
    output_tokens: int | None
    provider_request_id: str | None


def parse_retry_after(value: str | None) -> float | None:
    """Seconds from a Retry-After header: delta-seconds or an HTTP date."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(value)
    except TypeError, ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0.0, (moment - datetime.now(UTC)).total_seconds())


class OllamaAdapter:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # No pool limit: the gateway bounds concurrency, so an attempt never waits in the pool
        # and its timeout starts when the request leaves (Processing NFR-2). No timeout here
        # either: the gateway cancels the attempt, which closes its connection.
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=None,
            limits=httpx.Limits(max_connections=None, max_keepalive_connections=20),
            transport=transport or httpx.AsyncHTTPTransport(retries=0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        *,
        model: str,
        prompt: str,
        content: str,
        output_schema: type[BaseModel],
        settings: ModelSettings,
    ) -> AdapterResult:
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt},
                # The message goes as user content, never into the prompt (Processing FR-1).
                {"role": "user", "content": content},
            ],
            "format": output_schema.model_json_schema(),
            "stream": False,
            "think": settings.think,
            "options": settings.as_options(),
        }
        if settings.keep_alive is not None:
            body["keep_alive"] = settings.keep_alive
        try:
            response = await self._client.post("/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{type(exc).__name__}") from exc
        return self._classify(response, output_schema)

    def _classify(self, response: httpx.Response, output_schema: type[BaseModel]) -> AdapterResult:
        status = response.status_code
        if status == 429 or status >= 500:
            raise ProviderUnavailable(
                f"HTTP {status}", retry_after=parse_retry_after(response.headers.get("Retry-After"))
            )
        if status == 404:
            raise ProviderMisconfigured("HTTP 404")
        if status >= 400:
            raise ProviderRejected(f"HTTP {status}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise OutputInvalid("response is not JSON") from exc
        if not isinstance(payload, dict):
            raise OutputInvalid("response is not an object")
        if payload.get("done_reason") == "length":
            raise OutputInvalid("output cut off at the token limit")
        message = payload.get("message")
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise OutputInvalid("response has no message content")
        try:
            output = output_schema.model_validate(json.loads(text))
        except ValueError as exc:  # JSONDecodeError and ValidationError are both ValueErrors
            kind = "schema violation" if isinstance(exc, ValidationError) else "not JSON"
            raise OutputInvalid(f"output is {kind}") from exc
        return AdapterResult(
            output=output,
            input_tokens=_int_or_none(payload.get("prompt_eval_count")),
            output_tokens=_int_or_none(payload.get("eval_count")),
            provider_request_id=response.headers.get("X-Request-ID"),
        )

    async def warm_up(self, model: str, num_ctx: int) -> None:
        """Load the model and keep it loaded. A load request, not a model call (NFR-5).

        The context window is the one calls use: Ollama reloads a model whose loaded context
        differs from the request's.
        """
        response = await self._client.post(
            "/api/generate",
            json={"model": model, "keep_alive": -1, "options": {"num_ctx": num_ctx}},
            timeout=120,
        )
        response.raise_for_status()


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) else None
