import pytest

from app.services.prompts import (
    CandidateReview,
    InconsistentPromptState,
    PromptStatus,
    derive_status,
)

PROMOTED = CandidateReview(status="completed", outcome="promoted")


def test_the_active_version_is_active_whatever_its_review() -> None:
    assert derive_status(1, None, active_version_id=1, review=None) is PromptStatus.ACTIVE
    assert derive_status(2, 1, active_version_id=2, review=PROMOTED) is PromptStatus.ACTIVE


def test_the_seeded_version_is_superseded_once_another_is_active() -> None:
    assert derive_status(1, None, active_version_id=2, review=None) is PromptStatus.SUPERSEDED


def test_a_promoted_candidate_is_superseded_once_a_later_one_is_promoted() -> None:
    assert derive_status(2, 1, active_version_id=3, review=PROMOTED) is PromptStatus.SUPERSEDED


@pytest.mark.parametrize("review_status", ["pending", "running"])
def test_the_candidate_of_an_open_review_is_a_candidate(review_status: str) -> None:
    review = CandidateReview(status=review_status, outcome=None)
    assert derive_status(2, 1, active_version_id=1, review=review) is PromptStatus.CANDIDATE


@pytest.mark.parametrize("outcome", ["rejected", "no_changes", "no_proposal"])
def test_the_candidate_of_a_review_completed_without_promotion_is_rejected(outcome: str) -> None:
    review = CandidateReview(status="completed", outcome=outcome)
    assert derive_status(2, 1, active_version_id=1, review=review) is PromptStatus.REJECTED


def test_the_candidate_of_a_failed_review_is_abandoned() -> None:
    review = CandidateReview(status="failed", outcome=None)
    assert derive_status(2, 1, active_version_id=1, review=review) is PromptStatus.ABANDONED


def test_a_derived_version_without_a_review_is_inconsistent() -> None:
    with pytest.raises(InconsistentPromptState):
        derive_status(2, 1, active_version_id=1, review=None)


def test_an_unknown_review_status_is_inconsistent() -> None:
    with pytest.raises(InconsistentPromptState):
        derive_status(2, 1, active_version_id=1, review=CandidateReview("archived", None))
