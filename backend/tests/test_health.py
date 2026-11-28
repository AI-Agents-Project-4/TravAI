from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app


def test_health_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_reports_unreachable_database() -> None:
    # Nothing listens on port 1, so the connection is refused straight away.
    dead = create_engine(
        "postgresql+psycopg://nobody@127.0.0.1:1/nothing", connect_args={"connect_timeout": 2}
    )

    def broken_db() -> Iterator[Session]:
        with Session(dead) as session:
            yield session

    app.dependency_overrides[get_db] = broken_db
    try:
        response = TestClient(app).get("/health")
    finally:
        app.dependency_overrides.clear()
        dead.dispose()

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unreachable"}
