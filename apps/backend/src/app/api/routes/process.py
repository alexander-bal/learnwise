from typing import Annotated, Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.api.deps import ProcessingDep, TasksDep
from app.schemas.process import ErrorOut, ProcessIn, ProcessOut

router = APIRouter(tags=["process"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorOut} for status in (409, 422, 502, 503, 504)
}


@router.post("/process", response_model=ProcessOut, responses=_ERRORS)
async def process(
    payload: ProcessIn,
    request: Request,
    service: ProcessingDep,
    tasks: TasksDep,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=1, max_length=255)
    ] = None,
) -> JSONResponse:
    """Triage one message into a validated record (Processing FR-1)."""
    result = service.validate(payload.message)
    if result is None:
        result = await tasks.run(
            service.process(
                request_id=request.state.request_id,
                message=payload.message,
                body=await request.json(),
                idempotency_key=idempotency_key,
            )
        )
    request.state.log = result.log_fields
    return JSONResponse(result.body, status_code=result.status_code, headers=result.headers)
