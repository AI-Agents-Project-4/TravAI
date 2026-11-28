"""Settings, read from environment variables or the root `.env` file.

The root `.env` (copied from `.env.example`) is shared with docker-compose, so
values like POSTGRES_USER are in it too. Those are ignored here.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

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

    # --- Research agent (Kyle's code in researchAgent/) ---
    research_agent_dir: Path = REPO_ROOT / "researchAgent"
    # True = replay only from the research agent's on-disk cache; nothing goes out.
    # Tests and CI use this. A demo leaves it False (sandbox: Geoapify and tools-off
    # `claude -p` may run live, everything else is recorded data).
    research_offline: bool = False
    # Refetch the research agent's cached HTTP/LLM results older than this (README item 3).
    research_cache_ttl_hours: float | None = 24
    # Reuse a finished research run for an identical request newer than this, instead of
    # researching again (the "search cache" in Postgres). 0 turns reuse off.
    research_reuse_hours: float = 24
    # Days ahead to price a trip that has no start date (the form allows "flexible").
    default_start_in_days: int = 60

    # --- Planner agent ---
    # "cli": `claude -p` (Claude Code, the team's Claude plan; same as the research agent).
    # "api": Anthropic SDK with ANTHROPIC_API_KEY (e.g. the eval in GitHub Actions).
    # "none": no model; plans come from the rule-based fallback and say so.
    planner_llm: Literal["cli", "api", "none"] = "cli"
    planner_model: str = "claude-opus-5-5"
    planner_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    planner_timeout_seconds: int = 300
    # "two_agent": research -> planner reads the structured options (the design).
    # "single": one model call sees the whole research output and plans (eval baseline).
    agent_mode: Literal["two_agent", "single"] = "two_agent"

    # On startup, mark trips left mid-research by a restart as failed. Tests turn it off.
    recover_on_startup: bool = True

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
