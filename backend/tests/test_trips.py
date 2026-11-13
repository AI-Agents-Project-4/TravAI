import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.models import ProgressStep, Trip

EVAL_CASES = sorted((REPO_ROOT / "evals" / "cases").glob("*.json"))

TOKYO = {
    "origin": "DEN",
    "destination": "Tokyo, Japan",
    "start_date": "2027-03-10",
    "duration_days": 5,
    "travelers": 1,
    "budget": {"amount": 5000, "currency": "USD"},
    "transport_mode": "fly",
    "end_destination": None,
}


def test_create_trip_stores_the_request(client: TestClient, db_session: Session) -> None:
    response = client.post("/trips", json=TOKYO)

    assert response.status_code == 201
    body = response.json()
    assert body["warnings"] == []
    trip = db_session.get(Trip, uuid.UUID(body["trip_id"]))
    assert trip is not None
    assert trip.destination == "Tokyo, Japan"
    assert trip.budget_amount == Decimal("5000.00")
    assert trip.budget_currency == "USD"
    assert trip.status == "researching"


@pytest.mark.parametrize("case_file", EVAL_CASES, ids=lambda p: p.stem)
def test_every_eval_case_input_is_accepted(client: TestClient, case_file: Path) -> None:
    case = json.loads(case_file.read_text(encoding="utf-8"))
    if case["input"]["destination"] is None:
        pytest.skip("case input not filled in yet (destination is null)")
    response = client.post("/trips", json=case["input"])
    assert response.status_code == 201, response.text


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("destination", ""),
        ("duration_days", 0),
        ("travelers", 0),
        ("transport_mode", "boat"),
        ("budget", {"amount": 0, "currency": "USD"}),
        ("budget", {"amount": -5, "currency": "USD"}),
        ("budget", {"amount": 100, "currency": "usd"}),
        ("budget", {"amount": 100.123, "currency": "USD"}),
    ],
)
def test_create_trip_rejects_invalid_input(client: TestClient, field: str, value: Any) -> None:
    response = client.post("/trips", json={**TOKYO, field: value})
    assert response.status_code == 422


def test_progress_of_a_new_trip(client: TestClient) -> None:
    trip_id = client.post("/trips", json=TOKYO).json()["trip_id"]

    response = client.get(f"/trips/{trip_id}/progress")

    assert response.status_code == 200
    assert response.json() == {"status": "researching", "steps": []}


def test_progress_lists_steps_in_order(client: TestClient, db_session: Session) -> None:
    trip_id = uuid.UUID(client.post("/trips", json=TOKYO).json()["trip_id"])
    db_session.add_all(
        [
            ProgressStep(trip_id=trip_id, message="Searching flights"),
            ProgressStep(trip_id=trip_id, message="Found 4 flights, checking hotel prices"),
        ]
    )
    db_session.commit()

    steps = client.get(f"/trips/{trip_id}/progress").json()["steps"]

    assert [s["message"] for s in steps] == [
        "Searching flights",
        "Found 4 flights, checking hotel prices",
    ]
    assert all(s["at"] for s in steps)


def test_progress_of_unknown_trip_is_404(client: TestClient) -> None:
    response = client.get(f"/trips/{uuid.uuid4()}/progress")
    assert response.status_code == 404
