"""Test fixtures.

Tests run against a real Postgres, in a separate database named
`<your db>_test` (e.g. travai_test) so they never touch dev data. It's created
if missing and migrated from scratch once per test run. Each test runs inside
a transaction that is rolled back afterwards.

Override the database with TEST_DATABASE_URL if needed.
"""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, get_settings, to_sqlalchemy_url
from app.db import get_db
from app.main import app


def _test_database_url() -> str:
    if override := os.environ.get("TEST_DATABASE_URL"):
        return to_sqlalchemy_url(override)
    url = make_url(get_settings().sqlalchemy_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


def _create_database_if_missing(url_str: str) -> None:
    url = make_url(url_str)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
            )
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    except OperationalError as exc:
        raise RuntimeError(
            f"Can't reach Postgres at {url.host}:{url.port}. "
            "Start it from the repo root with `docker compose up -d db`."
        ) from exc
    finally:
        admin.dispose()


def _alembic_config() -> Config:
    config = Config(BACKEND_DIR / "alembic.ini")
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = _test_database_url()
    _create_database_if_missing(url)
    engine = create_engine(url)
    config = _alembic_config()
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        # Downgrade first so every run starts clean and exercises both directions.
        command.downgrade(config, "base")
        command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """A session whose commits only release savepoints; everything is rolled back at the end."""
    with engine.connect() as conn:
        outer = conn.begin()
        session = Session(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            session.close()
            outer.rollback()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
