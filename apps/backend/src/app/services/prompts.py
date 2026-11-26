from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PromptState, PromptVersion, Review
from app.models.review import OPEN_REVIEW_STATUSES


class PromptStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    CANDIDATE = "candidate"
    REJECTED = "rejected"
    ABANDONED = "abandoned"


class InconsistentPromptState(RuntimeError):
    pass


@dataclass(frozen=True)
class CandidateReview:
    """The review a version was proposed by: its status and, once completed, its outcome."""

    status: str
    outcome: str | None


@dataclass(frozen=True)
class PromptVersionView:
    id: int
    parent_id: int | None
    status: PromptStatus
    change_reason: str
    content: str
    created_at: str


def derive_status(
    version_id: int,
    parent_id: int | None,
    active_version_id: int,
    review: CandidateReview | None,
) -> PromptStatus:
    """A version's status is not stored; it follows from the active pointer and its review.

    Processing FR-2 and Prompt Improvement FR-2. The checks are ordered: a promoted candidate
    is active, or superseded once a later one is promoted, never a candidate.
    """
    if version_id == active_version_id:
        return PromptStatus.ACTIVE
    if review is None:
        # Only the seeded version has no review; it is superseded once anything is promoted.
        if parent_id is None:
            return PromptStatus.SUPERSEDED
        raise InconsistentPromptState(f"prompt version {version_id} has no review")
    if review.status == "completed" and review.outcome == "promoted":
        return PromptStatus.SUPERSEDED
    if review.status in OPEN_REVIEW_STATUSES:
        return PromptStatus.CANDIDATE
    if review.status == "completed":
        return PromptStatus.REJECTED
    if review.status == "failed":
        return PromptStatus.ABANDONED
    raise InconsistentPromptState(f"review of prompt version {version_id} is {review.status!r}")


async def list_prompt_versions(session: AsyncSession) -> list[PromptVersionView]:
    """Every prompt version, newest first."""
    active_version_id = await session.scalar(
        select(PromptState.active_version_id).where(PromptState.id == 1)
    )
    if active_version_id is None:
        raise InconsistentPromptState("prompt_state has no row")

    rows = await session.execute(
        select(PromptVersion, Review.status, Review.outcome)
        .outerjoin(Review, Review.candidate_prompt_id == PromptVersion.id)
        .order_by(PromptVersion.id.desc())
    )
    views = []
    for version, review_status, review_outcome in rows:
        review = (
            CandidateReview(status=review_status, outcome=review_outcome)
            if review_status is not None
            else None
        )
        views.append(
            PromptVersionView(
                id=version.id,
                parent_id=version.parent_id,
                status=derive_status(version.id, version.parent_id, active_version_id, review),
                change_reason=version.change_reason,
                content=version.content,
                created_at=version.created_at,
            )
        )
    return views
