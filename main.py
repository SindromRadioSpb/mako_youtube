"""
OpenClaw Mako YouTube Pipeline — FastAPI application entry point.

Start with:
    uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

import io
import sys

# Force UTF-8 stdout/stderr on Windows to handle non-ASCII content (Hebrew, etc.)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chart, youtube, review, admin
from app.infra.sa_models import Base, get_engine

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan handler.

    On startup:
        - Creates all database tables that do not yet exist (idempotent).
        - Logs a ready message.

    On shutdown:
        - Disposes the async engine connection pool gracefully.
    """
    engine = get_engine()
    log.info("openclaw_startup", message="Creating database tables if necessary...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("openclaw_startup", message="Database ready.")

    yield

    log.info("openclaw_shutdown", message="Disposing database engine...")
    await engine.dispose()
    log.info("openclaw_shutdown", message="Engine disposed.")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="OpenClaw Mako YouTube Pipeline",
    description=(
        "Semi-automatic music data ingestion and manual curation system "
        "for the Mako Hitlist chart. Scrapes chart data, extracts YouTube "
        "URLs, fetches video metadata, and provides a review workflow."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# CORS (permissive for local development — tighten for production)
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(chart.router)
app.include_router(youtube.router)
app.include_router(review.router)
app.include_router(admin.router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health", tags=["ops"], summary="Service health check")
async def health() -> dict:
    """
    Returns a simple health status.  Useful for load balancer probes.
    """
    return {"status": "ok", "service": "openclaw_mako_youtube"}
