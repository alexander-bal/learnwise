"""Processing a message into a validated triage record (Processing FR-1, FR-3, FR-4)."""

import json
import logging
import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import ProviderProfile, Settings
from app.llm.adapter import ModelSettings
from app.llm.call_log import CallContext, close_call
from app.llm.errors import LlmFailure, ProviderRejected
from app.llm.gateway import CallOutcome, LlmGateway
from app.llm.schemas import TriageRecord
from app.models import PromptState, PromptVersion, Sample
from app.services import idempotency
from app.services.idempotency import ClaimOutcome

log = logging.getLogger(__name__)

ENDPOINT = "/process"


@dataclass
class ProcessResult:
    status_code: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)
    # For the request's log line (Processing NFR-4).
    log_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActivePrompt:
    version_id: int
    content: str


class LeaseLost(Exception):
    pass


def error_body(code: str, message: str, *, retryable: bool) -> dict[str, Any]:
    return {"code": code, "message": message, "retryable": retryable}


def retry_after_header(seconds: float) -> dict[str, str]:
    return {"Retry-After": str(max(1, math.ceil(seconds)))}


async def active_prompt(session: AsyncSession) -> ActivePrompt:
    row = (
        await session.execute(
            select(PromptVersion.id, PromptVersion.content)
            .join(PromptState, PromptState.active_version_id == PromptVersion.id)
            .where(PromptState.id == 1)
        )
    ).one()
    return ActivePrompt(version_id=row.id, content=row.content)


class ProcessingService:
    def __init__(
        self,
        settings: Settings,
        *,
        read_sessionmaker: async_sessionmaker,
        write_sessionmaker: async_sessionmaker,
        gateway: LlmGateway,
        current_provider: Callable[[], ProviderProfile],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._read = read_sessionmaker
        self._write = write_sessionmaker
        self._gateway = gateway
        self._current_provider = current_provider
        self._clock = clock
        self.model_settings = ModelSettings(
            num_ctx=settings.processing_num_ctx,
            num_predict=settings.processing_num_predict,
            seed=settings.model_seed,
        )

    def validate(self, message: str) -> ProcessResult | None:
        """Refuse a message outside 1..max characters, before any model call."""
        if 1 <= len(message) <= self._settings.max_message_chars:
            return None
        return ProcessResult(
            422,
            error_body(
                "invalid_request",
                f"message must be 1 to {self._settings.max_message_chars} characters",
                retryable=False,
            ),
            log_fields={"error_code": "invalid_request", "idempotency": "none"},
        )

    async def process(
        self, *, request_id: str, message: str, body: Any, idempotency_key: str | None
    ) -> ProcessResult:
        deadline = self._clock() + self._settings.request_deadline_seconds
        # A request keeps the provider and the prompt it started with (FR-1, NFR-5).
        profile = self._current_provider()
        async with self._read() as session:
            prompt = await active_prompt(session)

        owner: str | None = None
        if idempotency_key is not None:
            async with self._write() as session, session.begin():
                claim = await idempotency.claim(
                    session,
                    endpoint=ENDPOINT,
                    key=idempotency_key,
                    body_hash=idempotency.request_hash(body),
                    lease_seconds=self._settings.idempotency_lease_seconds,
                )
            if claim.outcome is not ClaimOutcome.CLAIMED:
                return self._answer_claim(claim)
            owner = claim.owner_token
        idem = "claimed" if owner else "none"

        try:
            outcome = await self._gateway.call(
                CallContext(
                    operation="process", request_id=request_id, prompt_version_id=prompt.version_id
                ),
                profile=profile,
                model=profile.processing_model,
                prompt=prompt.content,
                content=message,
                output_schema=TriageRecord,
                model_settings=self.model_settings,
                deadline=deadline,
            )
        except LlmFailure as failure:
            return await self._fail(failure, idempotency_key, owner, prompt, idem)
        except BaseException:
            await self._release(idempotency_key, owner)
            raise

        try:
            return await self._store(
                request_id, message, profile, prompt, outcome, idempotency_key, owner, idem
            )
        except LeaseLost:
            async with self._write() as session, session.begin():
                await self._close_success(session, outcome, sample_id=None)
            log.warning("idempotency lease lost before the result was stored")
            return ProcessResult(
                409,
                error_body("request_in_progress", "The request is in progress", retryable=True),
                retry_after_header(1),
                {"error_code": "request_in_progress", "idempotency": idem},
            )
        except BaseException:
            await self._release(idempotency_key, owner)
            raise

    def _answer_claim(self, claim: idempotency.Claim) -> ProcessResult:
        match claim.outcome:
            case ClaimOutcome.REUSED:
                return ProcessResult(
                    422,
                    error_body(
                        "idempotency_key_reused",
                        "The idempotency key was used with a different request",
                        retryable=False,
                    ),
                    log_fields={"error_code": "idempotency_key_reused", "idempotency": "reused"},
                )
            case ClaimOutcome.REPLAYED:
                body = claim.response_body or {}
                return ProcessResult(
                    claim.response_status or 200,
                    body,
                    {"Idempotent-Replayed": "true"},
                    {
                        "error_code": body.get("code"),
                        "sample_id": body.get("sample_id"),
                        "prompt_version": body.get("prompt_version"),
                        "idempotency": "replayed",
                    },
                )
            case _:
                return ProcessResult(
                    409,
                    error_body("request_in_progress", "The request is in progress", retryable=True),
                    retry_after_header(claim.retry_after or 1),
                    {"error_code": "request_in_progress", "idempotency": "in_progress"},
                )

    async def _fail(
        self,
        failure: LlmFailure,
        key: str | None,
        owner: str | None,
        prompt: ActivePrompt,
        idem: str,
    ) -> ProcessResult:
        body = error_body(failure.code, failure.message, retryable=failure.retryable)
        headers: dict[str, str] = {}
        if failure.http_status == 503:
            retry_after = failure.retry_after
            if retry_after is None:
                retry_after = self._settings.default_retry_after_seconds
            headers = retry_after_header(retry_after)
        if key is not None and owner is not None:
            # ProviderRejected is decided by the request itself, so it is replayed; every
            # other failure can be retried (FR-4).
            final = isinstance(failure, ProviderRejected)
            async with self._write() as session, session.begin():
                await idempotency.finish(
                    session,
                    endpoint=ENDPOINT,
                    key=key,
                    owner_token=owner,
                    status="failed" if final else "retryable_failed",
                    response_status=failure.http_status if final else None,
                    response_body=body if final else None,
                )
        return ProcessResult(
            failure.http_status,
            body,
            headers,
            {"error_code": failure.code, "prompt_version": prompt.version_id, "idempotency": idem},
        )

    async def _store(
        self,
        request_id: str,
        message: str,
        profile: ProviderProfile,
        prompt: ActivePrompt,
        outcome: CallOutcome,
        key: str | None,
        owner: str | None,
        idem: str,
    ) -> ProcessResult:
        sample_id = uuid.uuid4().hex
        body = {
            "request_id": request_id,
            "sample_id": sample_id,
            "prompt_version": prompt.version_id,
            "record": outcome.output.model_dump(),
        }
        # The sample, its call's result and the key's completion: one transaction (FR-1).
        async with self._write() as session, session.begin():
            session.add(
                Sample(
                    id=sample_id,
                    request_id=request_id,
                    prompt_version_id=prompt.version_id,
                    input=message,
                    output=outcome.output.model_dump(),
                    provider=profile.name,
                    model=profile.processing_model,
                    model_config_=json.dumps(self.model_settings.as_config(), sort_keys=True),
                )
            )
            await session.flush()
            await self._close_success(session, outcome, sample_id=sample_id)
            if key is not None and owner is not None:
                held = await idempotency.finish(
                    session,
                    endpoint=ENDPOINT,
                    key=key,
                    owner_token=owner,
                    status="completed",
                    response_status=200,
                    response_body=body,
                    sample_id=sample_id,
                )
                if not held:
                    raise LeaseLost  # rolls the sample back: only the holder writes
        return ProcessResult(
            200,
            body,
            log_fields={
                "sample_id": sample_id,
                "prompt_version": prompt.version_id,
                "idempotency": idem,
            },
        )

    @staticmethod
    async def _close_success(
        session: AsyncSession, outcome: CallOutcome, *, sample_id: str | None
    ) -> None:
        await close_call(
            session,
            outcome.call_id,
            status="success",
            duration_ms=outcome.duration_ms,
            completed_at=outcome.completed_at,
            sample_id=sample_id,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            provider_request_id=outcome.provider_request_id,
        )

    async def _release(self, key: str | None, owner: str | None) -> None:
        """Leave the key retryable after an unexpected error, if the DB lets us."""
        if key is None or owner is None:
            return
        try:
            async with self._write() as session, session.begin():
                await idempotency.finish(
                    session,
                    endpoint=ENDPOINT,
                    key=key,
                    owner_token=owner,
                    status="retryable_failed",
                )
        except Exception:
            log.warning("could not release the idempotency key", exc_info=True)
