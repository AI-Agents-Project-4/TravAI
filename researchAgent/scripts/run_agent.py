"""Run the research agent on a test case. Usage: run_agent.py <case-id> [--offline]"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from research.agent import run

def main():
    cid = sys.argv[1]
    offline = "--offline" in sys.argv
    case = next(c for c in json.load(open(os.path.join(ROOT, "tests", "test_cases.json")))["cases"] if c["id"] == cid)
    t = time.time()
    out = run({**case["input"], "request_id": cid}, offline=offline)
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
