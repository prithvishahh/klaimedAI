"""FastAPI application factory (read-only Phase 0 surface)."""

from __future__ import annotations

from fastapi import FastAPI

from rcm.api.routes import router
from rcm.core.config import get_settings
from rcm.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.env != "dev")
    app = FastAPI(
        title="Medical RCM — Phase 0 (read-only)",
        version="0.0.0",
        description="Read-only denial ingest + triage. No outbound claim path.",
    )
    app.include_router(router)
    return app


app = create_app()
