import logging
import traceback

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.middleware import StoryContextMiddleware
from app.api.routes import router
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()
settings = get_settings()

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Added after CORS so it executes *inside* CORS (CORS wraps the response on the
# way out, this middleware binds context on the way in).
app.add_middleware(StoryContextMiddleware)
app.include_router(router, prefix=settings.api_prefix)


def _api_log_extra(request: Request, source: str) -> dict:
    story_id = getattr(request.state, "story_id", None) if hasattr(request, "state") else None
    run_id = getattr(request.state, "run_id", None) if hasattr(request, "state") else None
    return {
        "source": source,
        "story_id": story_id,
        "run_id": run_id,
        "method": request.method,
        "path": request.url.path,
    }


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    level = logging.ERROR if exc.status_code >= 500 else logging.WARNING
    logger.log(
        level,
        "HTTP exception",
        extra={
            **_api_log_extra(request, "api.http_exception"),
            "status_code": exc.status_code,
            "detail": str(exc.detail)[:500],
        },
    )
    headers = getattr(exc, "headers", None)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    logger.warning(
        "Request validation failed",
        extra={
            **_api_log_extra(request, "api.validation_error"),
            "status_code": 422,
            "errors": exc.errors(),
        },
    )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled exception",
        extra={
            **_api_log_extra(request, "api.unhandled"),
            "status_code": 500,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "traceback": traceback.format_exc()[-4000:],
        },
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
