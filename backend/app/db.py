"""Database engine, the per-request session, and sessions for background jobs."""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

# create_engine doesn't connect yet; the first query does.
engine = create_engine(get_settings().sqlalchemy_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

# Something that opens a session: `with factory() as session: ...`.
SessionFactory = Callable[[], AbstractContextManager[Session]]


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, closed afterwards.

    Routes commit explicitly. Anything not committed is rolled back on close.
    """
    with SessionLocal() as session:
        yield session


def get_session_factory() -> SessionFactory:
    """FastAPI dependency: how background jobs open their own sessions (tests override it)."""
    return SessionLocal
