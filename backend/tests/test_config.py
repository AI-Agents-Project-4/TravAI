import pytest

from app.config import to_sqlalchemy_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql://u:p@localhost:5432/db", "postgresql+psycopg://u:p@localhost:5432/db"),
        ("postgres://u:p@localhost/db", "postgresql+psycopg://u:p@localhost/db"),
        ("postgresql+psycopg://u@h/db", "postgresql+psycopg://u@h/db"),
    ],
)
def test_to_sqlalchemy_url(url: str, expected: str) -> None:
    assert to_sqlalchemy_url(url) == expected
