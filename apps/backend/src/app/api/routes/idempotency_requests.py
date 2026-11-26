from fastapi import APIRouter

from app.api.deps import Limit, Offset, SessionDep
from app.schemas.idempotency_requests import IdempotencyOut
from app.schemas.pagination import Page
from app.services import idempotency_requests

router = APIRouter(tags=["idempotency-requests"])


@router.get("/idempotency-requests")
async def list_idempotency_requests(
    session: SessionDep, limit: Limit = 50, offset: Offset = 0
) -> Page[IdempotencyOut]:
    """Idempotency records, newest first."""
    return Page[IdempotencyOut].model_validate(
        await idempotency_requests.list_idempotency(session, limit=limit, offset=offset)
    )
