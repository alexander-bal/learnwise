"""Idempotency records (Processing FR-3).

A key is claimed, or taken over, by one atomic write that only one request can win; the
outcome is written only by the holder of the lease.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.time import now_iso, parse_iso
from app.models import IdempotencyRequest


class ClaimOutcome(StrEnum):
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    REPLAYED = "replayed"
    REUSED = "reused"


@dataclass(frozen=True)
class Claim:
    outcome: ClaimOutcome
    owner_token: str | None = None
    response_status: int | None = None
    response_body: dict[str, Any] | None = None
    retry_after: float | None = None


def request_hash(body: Any) -> str:
    """A hash of the parsed body in canonical form: keys sorted, no insignificant whitespace."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


_CLAIM = text(
    """
    INSERT INTO idempotency_requests
        (endpoint, key, request_hash, status, owner_token, lease_expires_at,
         created_at, updated_at)
    VALUES (:endpoint, :key, :hash, 'processing', :owner, :lease, :now, :now)
    ON CONFLICT (endpoint, key) DO UPDATE SET
        status = 'processing',
        owner_token = excluded.owner_token,
        lease_expires_at = excluded.lease_expires_at,
        response_status = NULL,
        response_body = NULL,
        updated_at = excluded.updated_at
    WHERE idempotency_requests.request_hash = excluded.request_hash
      AND (idempotency_requests.status = 'retryable_failed'
           OR (idempotency_requests.status = 'processing'
               AND idempotency_requests.lease_expires_at < excluded.updated_at))
    RETURNING owner_token
    """
)


async def claim(
    session: AsyncSession, *, endpoint: str, key: str, body_hash: str, lease_seconds: float
) -> Claim:
    """Claim the key, take it over, or report what is stored. Commits nothing itself."""
    owner = uuid.uuid4().hex
    now = now_iso()
    won = await session.scalar(
        _CLAIM,
        {
            "endpoint": endpoint,
            "key": key,
            "hash": body_hash,
            "owner": owner,
            "lease": now_iso(lease_seconds),
            "now": now,
        },
    )
    if won == owner:
        return Claim(ClaimOutcome.CLAIMED, owner_token=owner)

    record = await session.get(IdempotencyRequest, (endpoint, key))
    if record is None:  # removed between the two statements; the caller may try again
        return Claim(ClaimOutcome.IN_PROGRESS, retry_after=1.0)
    if record.request_hash != body_hash:
        return Claim(ClaimOutcome.REUSED)
    if record.status in ("completed", "failed"):
        return Claim(
            ClaimOutcome.REPLAYED,
            response_status=record.response_status,
            response_body=record.response_body,
        )
    # `processing` with a valid lease, or a request that lost the race for it.
    retry_after = 1.0
    if record.lease_expires_at:
        lease_left = (parse_iso(record.lease_expires_at) - parse_iso(now)).total_seconds()
        retry_after = max(1.0, lease_left)
    return Claim(ClaimOutcome.IN_PROGRESS, retry_after=retry_after)


async def finish(
    session: AsyncSession,
    *,
    endpoint: str,
    key: str,
    owner_token: str,
    status: str,
    response_status: int | None = None,
    response_body: dict[str, Any] | None = None,
    sample_id: str | None = None,
) -> bool:
    """Write the outcome if this request still holds the lease. True when written."""
    result = await session.execute(
        update(IdempotencyRequest)
        .where(
            IdempotencyRequest.endpoint == endpoint,
            IdempotencyRequest.key == key,
            IdempotencyRequest.owner_token == owner_token,
            IdempotencyRequest.status == "processing",
        )
        .values(
            status=status,
            response_status=response_status,
            response_body=response_body,
            sample_id=sample_id,
            lease_expires_at=None,
            updated_at=now_iso(),
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1  # ty: ignore[missing-attribute]
