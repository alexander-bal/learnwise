import logging

from fastapi import APIRouter, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import SessionDep
from app.schemas.health import HealthOut
from app.services.health import schema_revision

log = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> HealthOut:
    return HealthOut(status="ok")


@router.get("/readyz")
async def readyz(request: Request, response: Response, session: SessionDep) -> HealthOut:
    """Ready when the DB is reachable and migrations are applied (Processing FR-6)."""
    try:
        revision = await schema_revision(session)
    except SQLAlchemyError:
        log.warning("readiness check could not reach the database", exc_info=True)
        revision = None
    if revision != request.app.state.head_revision:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthOut(status="unavailable")
    return HealthOut(status="ok")
