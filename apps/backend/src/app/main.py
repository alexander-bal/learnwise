from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app.api.middleware import RequestContextMiddleware
from app.api.routes import health, process, prompts, provider, records, reviews
from app.lifespan import lifespan


async def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = "not_found" if exc.status_code == 404 else "http_error"
    return JSONResponse(
        {"code": code, "message": str(exc.detail), "retryable": False},
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        {"code": "invalid_request", "message": "Invalid request", "retryable": False},
        status_code=422,
    )


def create_app() -> FastAPI:
    app = FastAPI(title="AI Ticket Triage Service", lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.include_router(health.router)
    app.include_router(prompts.router)
    app.include_router(process.router)
    app.include_router(records.router)
    app.include_router(provider.router)
    app.include_router(reviews.router)
    return app


app = create_app()
