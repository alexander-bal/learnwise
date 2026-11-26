import logging
import time
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_id import REQUEST_ID_HEADER, request_id_var, resolve_request_id

log = logging.getLogger("app.request")

# Fields a route may add to its request's log line, through request.state.log.
LOG_FIELDS = ("error_code", "sample_id", "prompt_version", "idempotency")


class RequestContextMiddleware:
    """Request id, the 500 fallback and the request's log line.

    Plain ASGI rather than BaseHTTPMiddleware, which cancels the endpoint when the client
    disconnects; a /process request must run to its end (Processing FR-3).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = resolve_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        state: dict[str, Any] = scope.setdefault("state", {})
        state["request_id"] = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            try:
                await self.app(scope, receive, send_with_id)
            except Exception:
                # Never leak a stack trace to the caller (Processing FR-1).
                log.exception("unhandled error")
                status_code = 500
                if not response_started:
                    response = JSONResponse(
                        {"code": "internal_error", "message": "Internal error", "retryable": True},
                        status_code=500,
                    )
                    await response(scope, receive, send_with_id)
        finally:
            route = scope.get("route")
            extra: dict[str, Any] = {
                "method": scope["method"],
                "route": getattr(route, "path", scope["path"]),
                "status": status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            }
            fields = state.get("log") or {}
            extra.update({k: fields[k] for k in LOG_FIELDS if fields.get(k) is not None})
            log.info("request finished", extra=extra)
            request_id_var.reset(token)
