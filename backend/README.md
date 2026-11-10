# TravAI backend — owner: Jake

Python/FastAPI service that the frontend calls. It runs the research and planner agents and stores their results in Postgres.

> **Status:** placeholder written by Fernando during repo setup. Jake is setting up the FastAPI project this week (11/9). **Jake: replace this README** with your own description and setup/run instructions.

Intended stack: Python, FastAPI, [uv](https://docs.astral.sh/uv/), Postgres (local DB: `docker compose up -d db` from the repo root, connection string in the root `.env` as `DATABASE_URL`).

```
backend/
  app/
    agents/
      research/   # Kyle: finds flights, hotels, activities and prices → writes options to the DB
      planner/    # Jake: reads options → 3 itineraries, feasibility, redraft
```

The endpoints and response shapes it serves are in [../docs/api-contract.md](../docs/api-contract.md).
