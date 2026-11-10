# Planner agent — owner: Jake

Turns the research agent's stored options into **three distinct itineraries** that fit the budget, or reports that the trip isn't feasible.

- **Input:** trip request, plus the `Option` rows from the DB (not the research agent's transcript).
- **Output:** 3 `Plan`s (title, flight, hotel, day-by-day schedule, cost breakdown, total vs. budget, warnings), **or** `feasible: false` with a reason and `min_estimated_cost`.
- **Checks:** budget, opening hours, travel time between items, and that the order makes sense for multi-stop trips.
- **Redraft:** takes the user's edited plan. Items with `locked: true` stay as they are. It refits the rest to the budget and returns `dropped_items` with reasons.

Must be testable with dummy option data before the research agent is finished. Keep fixtures in `backend/tests/`.
