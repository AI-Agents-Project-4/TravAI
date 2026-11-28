"""Slim view of a research output for the planner: same facts, far fewer tokens.

Keeps what the planner needs to check budget, hours and travel time, and drops descriptions, local names, notes and
provenance details. Full provenance stays in the stored output (look items up by `id`)."""
from __future__ import annotations


def _price(p: dict) -> dict:
    out = {"amt": round(p.get("amount_normalized", p["amount"]), 2), "basis": p["basis"], "type": p["price_type"]}
    return out


def planner_view(o: dict, *, max_activities: int = 60) -> dict:
    acts = sorted(o["activities"], key=lambda a: (a["confidence"]["level"] == "low", a["price"]["price_type"] == "estimate"))
    return {
        "request_id": o["request_id"], "status": o["status"], "currency": o["currency"],
        "feasibility": {k: o["feasibility"].get(k) for k in ("budget", "estimated_minimum_total", "verdict", "breakdown")},
        "advisories": [{"level": a["level"], "reliability": a.get("map_data_reliability"), "summary": a["summary"][:200]} for a in o["advisories"]],
        "flights": [{"id": f["id"], "dir": f["direction"], "price": _price(f["price"]), "stops": f["stops"],
                     "minutes": f["duration_minutes"],
                     "route": [(s["from"], s["depart_at"], s["to"], s["arrive_at"]) for s in f["segments"]]} for f in o["flights"]],
        "lodging": [{"id": l["id"], "name": l["name"], "area": l["area"], "night": _price(l["price"]), "rating": l.get("rating"),
                     "in": l["check_in"], "out": l["check_out"], "geo": [l["location"]["lat"], l["location"]["lng"]]} for l in o["lodging"]],
        "activities": [{"id": a["id"], "name": a["name"], "cat": a["category"], "area": a.get("area"), "price": _price(a["price"]),
                        "min": a["duration_minutes"], "geo": [a["location"]["lat"], a["location"]["lng"]],
                        **({"hours": a["hours"]} if "hours" in a else {}),
                        **({"trip_min": a["round_trip_from_base_minutes"]} if "round_trip_from_base_minutes" in a else {}),
                        **({"est": True} if a["price"]["price_type"] == "estimate" else {})} for a in acts[:max_activities]],
        "transport": [{"id": g["id"], "mode": g["mode"], "from": g["from"], "to": g["to"], "min": g["duration_minutes"],
                       **({"price": _price(g["price"])} if g.get("price") else {})} for g in o["ground_transport"]],
        "gaps": [f"{g['category']}: {g['reason']}" for g in o["gaps"]],
        "notes": o["notes"],
    }
