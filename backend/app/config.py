"""Settings, read from environment variables or the root `.env` file.

The root `.env` (copied from `.env.example`) is shared with docker-compose, so
values like POSTGRES_USER are in it too. Those are ignored here.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Later files win: backend/.env can override the shared root .env.
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
    )

    database_url: str = "postgresql://travai:travai@localhost:5432/travai"
    # Browser origins allowed to call the API (the Next.js dev server by default).
    # In .env, set as JSON: CORS_ORIGINS='["http://localhost:3000"]'
    cors_origins: list[str] = ["http://localhost:3000"]

    @property
    def sqlalchemy_url(self) -> str:
        return to_sqlalchemy_url(self.database_url)


def to_sqlalchemy_url(url: str) -> str:
    """Point a plain `postgresql://` URL at the psycopg 3 driver.

    `.env` keeps the standard form so other tools (psql, docker) can use it too.
    """
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
