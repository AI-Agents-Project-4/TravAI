"""Run test cases through the agent and check the output.

Usage: python3 tests/run_cases.py [case-id ...] [--gather]    (no ids = all cases)
Default is sandbox: replay from the cache, no network. --gather allows live lookups (spends API quota the first time;
every call is cached, so reruns are free).
Automated checks cover schema, status, counts, verdicts, sources and per-case rules. `must_hold` lines that need
a human (e.g. 'within 30% of a manual Google Flights check') are listed as MANUAL, not silently passed."""
import json, os, sys, time, traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# Sandbox by default: only --gather lets the agent reach the network (to collect new data into the cache).
if "--gather" in sys.argv:
    os.environ["TRAVAI_ALLOW_NETWORK"] = "1"
from research.agent import run

OUT = os.path.join(ROOT, "tests", "outputs")


def all_priced(o):
    for k in ("flights", "lodging", "activities"):
        for it in o[k]:
            yield k, it, it["price"]
            if "total_stay_price" in it:
                yield k, it, it["total_stay_price"]
    for it in o["ground_transport"]:
        if it.get("price"):
            yield "ground_transport", it, it["price"]


def generic_checks(o, case):
    f = []
    for k, it, p in all_priced(o):
        if not it.get("source", {}).get("url"):
            f.append(f"{k} {it['id']}: no source.url")
        if p["currency"] != o["currency"] and p["amount"] > 0 and not ("amount_normalized" in p and "fx_rate" in p):
            f.append(f"{k} {it['id']}: {p['currency']} price not normalized to {o['currency']}")
        if p["price_type"] == "estimate" and not p.get("estimate_method"):
            f.append(f"{k} {it['id']}: estimate without method")
    if "flight" not in case["input"]["transport_modes"] and o["flights"]:
        f.append("flights returned although flight is not an allowed mode")
    if o["status"] in ("ok", "partial") and o["feasibility"]["verdict"] == "likely_impossible":
        f.append("status/verdict mismatch")
    return f


def cats(o): return {a["category"] for a in o["activities"]}


CASE_CHECKS = {
    "tokyo-5d-5000": lambda o: (
        ([] if all(f["segments"][0]["from"] in ("DEN",) and f["segments"][-1]["to"] in ("DEN", "HND", "NRT") for f in o["flights"]) else ["flight endpoints are not DEN/HND/NRT"])
        + ([] if len(cats(o)) >= 3 else ["fewer than 3 activity categories"])
        + ([] if any(a["category"] == "day_trip" and a.get("round_trip_from_base_minutes") for a in o["activities"]) else ["no day_trip activities with round_trip_from_base_minutes"])),
    "cos-daytrip-500": lambda o: (
        ([] if any(g["mode"] == "drive" and 95 <= (g.get("distance_km") or 0) <= 130 and g["price"]["price_type"] == "estimate" for g in o["ground_transport"]) else ["no ~110 km drive leg with estimated fuel cost"])
        + ([] if sum(1 for a in o["activities"] if "hours" in a) >= 1 else ["no activity has opening hours"])),
    "europe-2w-10000": lambda o: (
        ([] if any(g["from"].startswith("Paris") and g["to"].startswith("Rome") for g in o["ground_transport"]) or any(f["direction"] == "intercity" and f["segments"][0]["from"] in ("CDG", "ORY", "BVA") for f in o["flights"]) else ["no Paris->Rome option"])
        + ([] if any(g["from"].startswith("Rome") and g["to"].startswith("Barcelona") for g in o["ground_transport"]) or any(f["direction"] == "intercity" and f["segments"][0]["from"] in ("FCO", "CIA") for f in o["flights"]) else ["no Rome->Barcelona option"])
        + ([] if all(f["price"]["basis"] == "total_all_travelers" for f in o["flights"]) else ["flight price basis not total_all_travelers for 2 travelers"])),
    "japan-month-500-impossible": lambda o: (
        ([] if (o["feasibility"]["estimated_minimum_total"] or 0) > 3 * 500 else ["estimated minimum is not well above budget"])
        + ([] if o["flights"] and o["lodging"] else ["did not return the cheapest flight/lodging it found"])),
    "ukraine-3d-1000-hard": lambda o: (
        ([] if any(a["level"] == "do_not_travel" for a in o["advisories"]) else ["no do_not_travel advisory"])
        + ([] if any(a["map_data_reliability"] in ("uncertain", "poor") for a in o["advisories"]) else ["map_data_reliability not flagged"])
        + ([] if o["activities"] or o["lodging"] or o["flights"] else ["no results returned so the user cannot proceed"])),
    "group-of-four": lambda o: (
        ([] if all(f["price"]["basis"] == "total_all_travelers" for f in o["flights"]) else ["flight basis wrong"])
        + ([] if any("rental" in g["id"] or g["mode"] == "drive" for g in o["ground_transport"]) else ["no car/drive option although drive allowed"])),
    "ambiguous-destination": lambda o: (
        ([] if any("Paris" in n and "France" in n for n in o["notes"]) or any(a.get("area") for a in o["activities"]) else [])
        + ([] if o["activities"] and all(48.7 < a["location"]["lat"] < 49.0 and 2.0 < a["location"]["lng"] < 2.7
                                         for a in o["activities"] if a["category"] != "day_trip") else ["activities are not located in Paris, France"])),
    "remote-sparse-data": lambda o: ([] if o["gaps"] else ["no gaps reported for a destination with sparse data"]),
    "invalid-past-date": lambda o: ([] if any("past" in (g["reason"] + " ".join(o["notes"])) for g in o["gaps"]) else ["past date not mentioned"]),
    "invalid-zero-budget": lambda o: ([] if o["status"] in ("error", "infeasible") and not o["flights"] else ["zero budget triggered searches"]),
    "non-usd-budget": lambda o: ([] if o["currency"] == "GBP" else ["top-level currency is not GBP"]),
    "solo-budget-cheap-regional": lambda o: [],
    "tight-budget-borderline": lambda o: ([] if o["feasibility"]["verdict"] != "comfortable" else ["labelled comfortable"]),
}


def check(case, o):
    e = case["expect"]
    fails = [f"schema: {x}" for x in o["_schema_errors"]]
    if "status" in e and o["status"] != e["status"]:
        fails.append(f"status {o['status']} != {e['status']}")
    if "status_in" in e and o["status"] not in e["status_in"]:
        fails.append(f"status {o['status']} not in {e['status_in']}")
    for k, n in e.get("min_counts", {}).items():
        if len(o[k]) < n:
            fails.append(f"{k}: {len(o[k])} < min {n}")
    for k, n in e.get("max_counts", {}).items():
        if len(o[k]) > n:
            fails.append(f"{k}: {len(o[k])} > max {n}")
    if "feasibility_verdict_in" in e and o["feasibility"]["verdict"] not in e["feasibility_verdict_in"]:
        fails.append(f"verdict {o['feasibility']['verdict']} not in {e['feasibility_verdict_in']}")
    fails += generic_checks(o, case)
    fails += CASE_CHECKS.get(case["id"], lambda o: [])(o)
    return fails


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    offline = "--offline" in sys.argv
    cases = json.load(open(os.path.join(ROOT, "tests", "test_cases.json")))["cases"]
    cases = [c for c in cases if not args or c["id"] in args]
    os.makedirs(OUT, exist_ok=True)
    rows, total_fail = [], 0
    for c in cases:
        t = time.time()
        try:
            o = run({**c["input"], "request_id": c["id"]}, offline=offline)
            json.dump(o, open(os.path.join(OUT, c["id"] + ".json"), "w"), indent=2, ensure_ascii=False)
            fails = check(c, o)
            manual = [m for m in c["expect"].get("must_hold", []) if any(w in m for w in ("manual", "within", "LLM"))]
            rows.append((c["id"], o["status"], f"F{len(o['flights'])} L{len(o['lodging'])} A{len(o['activities'])} T{len(o['ground_transport'])}",
                         o["feasibility"]["verdict"], fails, manual, int(time.time() - t)))
        except Exception as ex:
            traceback.print_exc()
            rows.append((c["id"], "CRASH", "", "", [f"{type(ex).__name__}: {str(ex)[:160]}"], [], int(time.time() - t)))
        total_fail += bool(rows[-1][4])
        print(f"{'PASS' if not rows[-1][4] else 'FAIL'} {rows[-1][0]} ({rows[-1][6]}s)", flush=True)
    lines = ["# Test run", "", "| case | result | status | counts | verdict |", "|---|---|---|---|---|"]
    for cid, st, n, v, fails, manual, secs in rows:
        lines.append(f"| {cid} | {'PASS' if not fails else 'FAIL'} | {st} | {n} | {v} |")
    lines.append("")
    for cid, st, n, v, fails, manual, secs in rows:
        if fails or manual:
            lines.append(f"## {cid}")
            lines += [f"- FAIL: {f}" for f in fails] + [f"- MANUAL: {m}" for m in manual]
            lines.append("")
    open(os.path.join(OUT, "report.md"), "w").write("\n".join(lines))
    print("\n".join(lines))
    print(f"\n{len(rows) - total_fail}/{len(rows)} cases pass automated checks")
    sys.exit(1 if total_fail else 0)

main()
