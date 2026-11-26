import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.core.request_id import REQUEST_ID_HEADER, request_id_var, resolve_request_id

log = logging.getLogger("app.request")


async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    status_code = 500
    try:
        try:
            response = await call_next(request)
        except Exception:
            # Never leak a stack trace to the caller (Processing FR-1).
            log.exception("unhandled error")
            response = JSONResponse(
                {"code": "internal_error", "message": "Internal error", "retryable": True},
                status_code=500,
            )
        status_code = response.status_code
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
    finally:
        route = request.scope.get("route")
        log.info(
            "request finished",
            extra={
                "method": request.method,
                "route": getattr(route, "path", request.url.path),
                "status": status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        request_id_var.reset(token)
