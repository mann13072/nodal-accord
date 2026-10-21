"""API latency against a generated dataset (blueprint §12.3 targets: case index p95 < 2 s, open case p95 < 3 s).

Runs the real FastAPI app in-process (TestClient, no network), with a fresh SQLite workflow DB. Measures cold (first
request, includes lazy table loading and index builds) and warm (repeated) latency.

    python tests/benchmark/load_api.py --data-root <dataset dir> --repeats 20
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for sub in ("packages/domain/src", "packages/planning_engine/src", "packages/optimization_engine/src", "packages/finance_engine/src",
            "packages/integrations/src", "apps/api/src"):
    sys.path.insert(0, str(REPO / sub))

from fastapi.testclient import TestClient  # noqa: E402

from nodal_api.config import Settings  # noqa: E402
from nodal_api.main import create_app  # noqa: E402


def timed(client, path, headers):
    t = time.perf_counter()
    r = client.get(path, headers=headers)
    dt = time.perf_counter() - t
    assert r.status_code == 200, (path, r.status_code, r.text[:200])
    return dt, r.json()


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--repeats", type=int, default=20)
    ap.add_argument("--principal", default="demo.buyer001.planner")
    ap.add_argument("--out", default=str(REPO / "docs" / "evaluation"))
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp())
    settings = Settings(env="bench", demo_mode=True, data_root=Path(args.data_root).resolve(),
                        db_url=f"sqlite:///{(tmp / 'bench.db').as_posix()}", inline_worker=False)
    H = {"X-Demo-Principal": args.principal}
    t0 = time.perf_counter()
    with TestClient(create_app(settings)) as c:
        startup = time.perf_counter() - t0
        results = {}
        cold, listing = timed(c, "/api/v1/cases?limit=200", H)
        case_ids = [x["case_id"] for x in listing["items"]]
        warm = [timed(c, "/api/v1/cases?limit=200", H)[0] for _ in range(args.repeats)]
        results["GET /cases"] = {"cold_s": round(cold, 4), "warm_p50_s": round(statistics.median(warm), 4), "warm_p95_s": round(pct(warm, .95), 4),
                                 "cases_visible": listing["total"]}
        for label, tmpl in (("GET /cases/{id}", "/api/v1/cases/{}"), ("GET /network/impact", "/api/v1/network/impact?case_id={}")):
            cold, _ = timed(c, tmpl.format(case_ids[0]), H)
            warm = [timed(c, tmpl.format(case_ids[i % len(case_ids)]), H)[0] for i in range(args.repeats)]
            results[label] = {"cold_s": round(cold, 4), "warm_p50_s": round(statistics.median(warm), 4), "warm_p95_s": round(pct(warm, .95), 4)}
        _, impact = timed(c, f"/api/v1/network/impact?case_id={case_ids[0]}", H)
    report = {"dataset": Path(args.data_root).name, "startup_s": round(startup, 3), "principal": args.principal, "repeats": args.repeats,
              "endpoints": results, "impact_nodes_example": len(impact["nodes"]),
              "method": "In-process TestClient, single client, sequential requests; cold = first request after startup."}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"api-latency-{Path(args.data_root).name}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
