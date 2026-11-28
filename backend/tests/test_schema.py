"""The database itself enforces the product rules it can (see app/models.py)."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base, Option


def test_migrations_match_models(engine: Engine) -> None:
    """Fails if someone changes app/models.py without adding a migration."""
    with engine.connect() as conn:
        diff = compare_metadata(
            MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata
        )
    assert diff == []


def _option(**overrides: Any) -> Option:
    fields: dict[str, Any] = {
        "destination": "tokyo, japan",
        "kind": "activity",
        "title": "Senso-ji Temple",
        "price_amount": Decimal("0"),
        "price_currency": "JPY",
        "price_is_estimate": False,
        "source_url": "https://example.com/sensoji",
        "fetched_at": datetime(2026, 11, 13, tzinfo=UTC),
    }
    return Option(**(fields | overrides))


def test_option_with_source_is_stored(db_session: Session) -> None:
    db_session.add(_option())
    db_session.commit()


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_url": ""},  # product rule 2: every price has a source
        {"price_amount": Decimal("-1")},
        {"kind": "spaceship"},
    ],
    ids=["empty source_url", "negative price", "unknown kind"],
)
def test_option_constraints(db_session: Session, overrides: dict[str, Any]) -> None:
    db_session.add(_option(**overrides))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_option_requires_fetched_at(db_session: Session) -> None:
    db_session.add(_option(fetched_at=None))
    with pytest.raises(IntegrityError):
        db_session.flush()
