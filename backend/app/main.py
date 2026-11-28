"""FastAPI entry point. Run with: uv run uvicorn app.main:app --reload"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, update

from app.config import get_settings
from app.db import SessionFactory, get_session_factory
from app.integration.research_agent import check_network_policy
from app.models import ProgressStep, Trip
from app.routes import health, plans, trips

log = logging.getLogger(__name__)

INTERRUPTED = "The server restarted while this trip was being planned. Please start it again."


def recover_interrupted_trips(factory: SessionFactory) -> None:
    """Trips that were mid-research when the server stopped will never finish: say so."""
    with factory() as db:
        stuck = list(
            db.scalars(select(Trip.id).where(Trip.status.in_(("researching", "planning"))))
        )
        if not stuck:
            return
        db.execute(
            update(Trip)
            .where(Trip.id.in_(stuck))
            .values(status="failed", failure_reason=INTERRUPTED)
        )
        db.add_all(ProgressStep(trip_id=t, message=INTERRUPTED) for t in stuck)
        db.commit()
        log.warning("marked %d interrupted trips as failed", len(stuck))


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        check_network_policy()  # never run research with full network access
        if get_settings().recover_on_startup:
            try:
                recover_interrupted_trips(get_session_factory())
            except Exception:  # a down database shouldn't stop the server starting (see /health)
                log.exception("could not check for interrupted trips")
        yield

    app = FastAPI(title="TravAI API", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(trips.router)
    app.include_router(plans.router)
    return app


app = create_app()
