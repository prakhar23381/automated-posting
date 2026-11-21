"""Application entry point.

Run with: uvicorn app.main:app --host 0.0.0.0 --port 4000
"""

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.api.routes import router
from app.config import Settings, get_settings
from app.errors import register_exception_handlers
from app.logging_config import configure_logging, request_id_var
from app.platforms.registry import build_platforms
from app.services.posting_service import PostingService
from app.services.public_check import PublicAccessChecker
from app.utils.http import create_client

logger = logging.getLogger("app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        api_client = create_client(settings.http_timeout)
        public_client = create_client(settings.public_check_timeout)
        platforms = build_platforms(settings)
        app.state.public_client = public_client
        app.state.posting_service = PostingService(
            platforms=platforms,
            client=api_client,
            public_checker=PublicAccessChecker(
                public_client, settings.public_check_timeout, settings.public_check_enabled
            ),
            settings=settings,
        )
        configured = [p.name for p in platforms if p.is_configured()]
        logger.info("startup platforms=%d configured=%s", len(platforms), configured or "none")
        try:
            yield
        finally:
            await api_client.aclose()
            await public_client.aclose()

    app = FastAPI(
        title="Automated Multi-Platform Posting API",
        version="1.0.0",
        description=(
            "Publishes one short message with a CTA link to several third-party platforms "
            "(Telegram, Mastodon, Bluesky, GitHub Gist, Telegraph, Dev.to, Hugging Face, "
            "Discord) and reports where each post lives and whether it is public."
        ),
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "request method=%s path=%s status=%d duration_ms=%d",
                request.method,
                request.url.path,
                response.status_code,
                (time.perf_counter() - started) * 1000,
            )
            return response
        finally:
            request_id_var.reset(token)

    register_exception_handlers(app)
    app.include_router(router)
    return app


app = create_app()
