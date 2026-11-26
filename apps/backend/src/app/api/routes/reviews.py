from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api.deps import ProvidersDep, SessionDep
from app.core.config import get_settings
from app.schemas.records import Page
from app.schemas.reviews import ReviewDetailOut, ReviewInProgressOut, ReviewOut, ReviewStartOut
from app.services import reviews

router = APIRouter(prefix="/reviews", tags=["reviews"])


def _in_progress(review_id: str) -> JSONResponse:
    body = ReviewInProgressOut(
        code="review_in_progress",
        message="A review is already open",
        retryable=True,
        review_id=review_id,
    )
    return JSONResponse(body.model_dump(), status_code=409)


@router.post(
    "",
    status_code=202,
    response_model=ReviewStartOut,
    responses={409: {"model": ReviewInProgressOut}},
)
async def start_review(request: Request, providers: ProvidersDep) -> JSONResponse:
    """Start a review; the worker runs it (Prompt Improvement FR-1). Only writes a row."""
    write = request.app.state.write_sessionmaker
    try:
        async with write() as session, session.begin():
            review = await reviews.start_review(
                session,
                request_id=request.state.request_id,
                profile=providers.current,
                settings=get_settings(),
            )
    except reviews.ReviewInProgress as exc:
        return _in_progress(exc.review_id)
    except IntegrityError:
        # Another request opened one between our check and our insert.
        async with request.app.state.sessionmaker() as session:
            open_id = await reviews.open_review_id(session)
        if open_id is None:
            raise
        return _in_progress(open_id)
    body = ReviewStartOut(review_id=review.id, status=review.status)
    return JSONResponse(body.model_dump(), status_code=202)


@router.get("")
async def list_reviews(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ReviewOut]:
    """Reviews, newest first, with their scores so far. For the console."""
    return Page[ReviewOut].model_validate(
        await reviews.list_reviews(session, limit=limit, offset=offset)
    )


@router.get("/{review_id}")
async def get_review(review_id: str, session: SessionDep) -> ReviewDetailOut:
    """One review with its prompts, judgments and calls. For the console."""
    detail = await reviews.review_detail(session, review_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="No such review")
    return ReviewDetailOut.model_validate(detail)
