"""
main.py — FastAPI application factory
=======================================
Entry point for Uvicorn::

    uvicorn app.main:app --reload --port 8000

OpenAPI docs are available at:
    http://localhost:8000/docs   (Swagger UI)
    http://localhost:8000/redoc  (ReDoc)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import analysis, measurements, reports
from app.api.store import InMemoryStore
from app.core.config import settings

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: create / tear down application-scoped resources
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    FastAPI lifespan context manager.

    Runs setup code before the first request is handled and teardown code
    after the last request completes (or on SIGTERM).
    """
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)
    app.state.store = InMemoryStore()
    yield
    logger.info("Shutting down — releasing resources.")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Automated Lab Measurement and Analysis Platform.  "
            "Upload oscilloscope CSV data or generate mock waveforms, "
            "run signal analysis, and generate PDF test reports."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ---- CORS ------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- Routers ---------------------------------------------------------
    app.include_router(
        measurements.router,
        prefix="/measurements",
        tags=["Measurements"],
    )
    app.include_router(
        analysis.router,
        prefix="/analysis",
        tags=["Analysis"],
    )
    app.include_router(
        reports.router,
        prefix="/reports",
        tags=["Reports"],
    )

    # ---- Health / root ---------------------------------------------------
    @app.get("/", tags=["Health"], summary="Health check")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": settings.app_name,
            "version": settings.app_version,
        }

    return app


app = create_app()
