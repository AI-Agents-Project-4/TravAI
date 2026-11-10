# Research agent — owner: Kyle

Finds flights, hotels, local transport and activities for a trip, with real prices and source links, and saves each one as an `Option` in Postgres for the planner.

- **Input:** trip request (origin, destination, dates/duration, travelers, budget, transport mode). See `POST /trips` in [docs/api-contract.md](../../../../docs/api-contract.md).
- **Output:** `Option` rows (`kind`, `title`, `price` with taxes and fees included, `price_is_estimate`, `source_url`, `fetched_at`, location, hours, …), plus short progress messages for the UI ("Found 4 flights, checking hotel prices").
- **Decides:** what to search next based on what it has found, when there are enough options to stop, and whether a source is trustworthy.
- **Must:** never invent prices, mark estimates as estimates and round them up, and reuse cached options that are still fresh.

Week of 11/9: survey which research tools and APIs exist, and how accessible and expensive they are. Record the findings here or in `docs/`.
