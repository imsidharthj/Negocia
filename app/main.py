"""
Negocia — Omi Integration Backend

FastAPI application factory.
Mounts routers, configures middleware, logging, and exception handlers.
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import health, insights, webhook
from app.config import get_settings
from app.middleware import RequestLoggingMiddleware

logger = logging.getLogger("negocia")


def _configure_logging() -> None:
    """Set up structured logging for the application."""
    settings = get_settings()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()
    root.addHandler(handler)

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    Startup logic runs before ``yield``, shutdown logic runs after.
    """
    settings = get_settings()
    logger.info(
        "🚀 %s v%s starting up [%s]",
        settings.app_name,
        settings.app_version,
        settings.environment,
    )
    yield
    logger.info("👋 %s shutting down", settings.app_name)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    _configure_logging()
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Real-time sales negotiation insights powered by Omi AI transcription.",
        lifespan=lifespan,
    )

    # --- Exception Handlers ---
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Catch unhandled exceptions and return a clean 500 response."""
        logger.exception(
            "Unhandled error | %s %s | %s",
            request.method,
            request.url.path,
            str(exc),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "detail": "An unexpected error occurred. Please try again later.",
            },
        )

    # --- Middleware (order matters: last added = first executed) ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLoggingMiddleware)

    # --- Routers ---
    app.include_router(health.router)
    app.include_router(webhook.router)
    app.include_router(insights.router)

    return app


# Module-level app instance for uvicorn
app = create_app()
