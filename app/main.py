"""Application entry point: wiring, lifespan, middleware, routers."""

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import contact, health, metrics
from app.core.config import get_settings
from app.core.database import close_db, verify_schema
from app.core.errors import register_exception_handlers
from app.core.logging import RequestLoggingMiddleware, setup_logging
from app.repositories.ratelimit_repo import RateLimiter
from app.services.ai.service import build_ai_service
from app.services.contact_service import ContactService
from app.services.mail_service import MailService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings)
    logger.info("Starting %s (%s)", settings.app_name, settings.environment)

    # Schema is owned by Alembic, not by the app. Calling create_all() here too
    # would give the project two sources of truth that drift apart the first time
    # a migration does something create_all() cannot express.
    # Migrations run in the container entrypoint (see docker-entrypoint.sh) and
    # in the documented local setup.
    await verify_schema()

    # Built once and reused: these hold HTTP clients and in-memory state.
    rate_limiter = RateLimiter(
        max_requests=settings.rate_limit_max_requests,
        window_seconds=settings.rate_limit_window_seconds,
        state_path=settings.rate_limit_state_path,
    )
    rate_limiter.load()

    ai_service = build_ai_service(settings)
    mail_service = MailService(settings)

    app.state.settings = settings
    app.state.rate_limiter = rate_limiter
    app.state.ai_service = ai_service
    app.state.mail_service = mail_service
    app.state.contact_service = ContactService(ai_service, mail_service)

    logger.info("AI providers configured: %s", ai_service.available_providers or "none")
    logger.info("SMTP configured: %s", settings.mail_configured)

    yield

    # Flush counters so a restart does not hand everyone a fresh quota.
    await rate_limiter.save()
    await close_db()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Backend for a developer landing page: validated contact form, "
            "AI analysis of incoming messages with provider fallback, "
            "email notifications, file-based request logging and rate limiting."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Order matters: request logging wraps CORS so preflight requests are logged too.
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )

    register_exception_handlers(app, debug=settings.debug)

    api = APIRouter(prefix="/api")
    api.include_router(contact.router)
    api.include_router(health.router)
    api.include_router(metrics.router)
    app.include_router(api)

    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "health": "/api/health",
        }

    return app


app = create_app()
