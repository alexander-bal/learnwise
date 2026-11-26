from dataclasses import asdict

from fastapi import APIRouter

from app.api.deps import SessionDep
from app.schemas.prompts import PromptVersionOut
from app.services.prompts import list_prompt_versions

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.get("")
async def list_prompts(session: SessionDep) -> list[PromptVersionOut]:
    """Every prompt version, newest first, with its derived status."""
    return [PromptVersionOut(**asdict(v)) for v in await list_prompt_versions(session)]
