"""Run the research agent on a test case. Usage: run_agent.py <case-id> [--gather] [--sandbox] [--offline]

Default is the SANDBOX: flights and hotels come from the recorded sandbox data (nearest match for trips that were not
recorded), everything else is replayed from the cache, and only Geoapify may be reached live.
--gather   allow the network (cache-first, spends API quota, fills the cache). Only for collecting data.
--sandbox  with --gather: still take flights and hotels from the recorded sandbox data, everything else live
--offline  replay every call from the cache, Geoapify included: no network at all"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Sandbox by default: only --gather lets the agent reach the network (to collect new data into the cache).
if "--gather" in sys.argv:
    os.environ["TRAVAI_ALLOW_NETWORK"] = "1"
sys.path.insert(0, ROOT)
from research.agent import run

def main():
    cases = json.load(open(os.path.join(ROOT, "tests", "test_cases.json")))["cases"]
    ids = [c["id"] for c in cases]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    bad = [f for f in flags if f not in ("--offline", "--sandbox", "--gather")]
    if len(args) != 1 or args[0] not in ids or bad:
        problem = (f"unknown option {bad[0]}" if bad else "missing case id" if not args
                   else f"unknown case id {args[0]!r}" if len(args) == 1 else "give exactly one case id")
        sys.exit(f"{problem}\nusage: run_agent.py <case-id> [--gather] [--sandbox] [--offline]\ncase ids:\n  " + "\n  ".join(ids))
    cid = args[0]
    offline = "--offline" in flags
    case = next(c for c in cases if c["id"] == cid)
    t = time.time()
    out = run({**case["input"], "request_id": cid}, offline=offline, data_mode_override="sandbox" if "--sandbox" in sys.argv else None)
    os.makedirs(os.path.join(ROOT, "tests", "outputs"), exist_ok=True)
    path = os.path.join(ROOT, "tests", "outputs", cid + ".json")
    json.dump(out, open(path, "w"), indent=2, ensure_ascii=False)
    f = out["feasibility"]
    print(f"{cid}: status={out['status']} flights={len(out['flights'])} lodging={len(out['lodging'])} activities={len(out['activities'])} "
          f"transport={len(out['ground_transport'])} advisories={len(out['advisories'])} verdict={f['verdict']} min_total={f['estimated_minimum_total']} "
          f"({time.time()-t:.0f}s)")
    print("schema errors:", len(out["_schema_errors"]), *out["_schema_errors"][:8], sep="\n  ")
    print("gaps:", *[f"{g['category']}: {g['reason']}" for g in out["gaps"]], sep="\n  ")
    print("wrote", path)

main()
