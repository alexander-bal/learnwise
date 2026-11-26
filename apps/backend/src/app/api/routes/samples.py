from fastapi import APIRouter

from app.api.deps import Limit, Offset, SessionDep
from app.schemas.pagination import Page
from app.schemas.samples import SampleOut
from app.services import samples

router = APIRouter(tags=["samples"])


@router.get("/samples")
async def list_samples(
    session: SessionDep, limit: Limit = 50, offset: Offset = 0
) -> Page[SampleOut]:
    """Stored samples, newest first."""
    return Page[SampleOut].model_validate(
        await samples.list_samples(session, limit=limit, offset=offset)
    )
