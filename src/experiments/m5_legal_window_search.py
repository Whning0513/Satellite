"""
m5_legal_window_search.py
=========================
Legal 2026 launch-window search for complete-return lunar trajectories.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(_REPO / "src"))

from horizons import fetch_sem_vectors
from mission_constraints import MISSION_LAUNCH_END_DATE, MISSION_LAUNCH_START_DATE

from experiments.legal_window_search_tools import (
    SearchConfig,
    default_rm_values,
    evaluate_lunar_candidate,
    legal_coarse_t0_values,
    legal_refine_t0_values,
    summarize_legal_window_results,
)


RESULTS = _REPO / "data" / "results"
_BODY_DATA = None


def _candidate_rank(row: dict) -> tuple:
    return (
        0 if row["fair"] else 1,
        0 if row["valid_return_event"] else 1,
        float(row["distance_to_earth_km"]) if row["distance_to_earth_km"] is not None else float("inf"),
        float(row["perihelion_error_AU"]),
    )


def _iter_jobs(config: SearchConfig) -> list[tuple[float, str, float]]:
    return [
        (float(t0), str(side), float(r_m_km))
        for t0 in config.t0_values
        for side in config.sides
        for r_m_km in config.r_m_values_km
    ]


def _worker_init() -> None:
    global _BODY_DATA
    if _BODY_DATA is None:
        _BODY_DATA = fetch_sem_vectors(use_cache=True)


def _worker_eval(payload: tuple[SearchConfig, float, str, float]) -> dict:
    global _BODY_DATA
    if _BODY_DATA is None:
        _worker_init()
    config, t0, side, r_m_km = payload
    return evaluate_lunar_candidate(_BODY_DATA, t0, side, r_m_km, config=config)


def _run_grid(body_data: dict, config: SearchConfig, *, max_workers: int) -> list[dict]:
    rows = []
    jobs = _iter_jobs(config)
    total = len(jobs)
    done = 0
    started = time.time()
    if max_workers <= 1:
        for t0, side, r_m_km in jobs:
            done += 1
            row = evaluate_lunar_candidate(body_data, t0, side, r_m_km, config=config)
            rows.append(row)
            if done % 25 == 0 or done == total:
                print(f"  progress {done}/{total} ({time.time()-started:.0f}s)")
        return rows

    with ProcessPoolExecutor(max_workers=max_workers, initializer=_worker_init) as pool:
        for row in pool.map(_worker_eval, [(config, t0, side, r_m_km) for t0, side, r_m_km in jobs], chunksize=1):
            done += 1
            rows.append(row)
            if done % 25 == 0 or done == total:
                print(f"  progress {done}/{total} ({time.time()-started:.0f}s)")
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--coarse-step-days", type=int, default=10)
    parser.add_argument("--top-k-seeds", type=int, default=8)
    parser.add_argument("--output", type=str, default=str(RESULTS / "m5_legal_window_search.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print("=" * 66)
    print("M5 legal 2026 window search")
    print("=" * 66)
    started_total = time.time()
    body_data = fetch_sem_vectors(use_cache=True)

    coarse_cfg = SearchConfig(
        t0_values=legal_coarse_t0_values(args.coarse_step_days),
        r_m_values_km=default_rm_values(),
        sides=["trailing", "leading"],
        trajectory_dt_integrate_s=3600.0,
        coarse_step_days=2.0,
        refine_step_s=3600.0,
        nominal_window_half_width_days=120.0,
        fallback_window_half_width_days=260.0,
    )
    print(f"coarse t0 count = {len(coarse_cfg.t0_values)}")
    coarse_rows = _run_grid(body_data, coarse_cfg, max_workers=max(1, int(args.max_workers)))
    coarse_rows_sorted = sorted(coarse_rows, key=_candidate_rank)

    seed_t0 = [row["t0_mjd"] for row in coarse_rows_sorted[: max(1, int(args.top_k_seeds))]]
    refine_t0 = legal_refine_t0_values(seed_t0, offsets_days=[-3, -2, -1, -0.5, 0, 0.5, 1, 2, 3])
    refine_cfg = SearchConfig(
        t0_values=refine_t0,
        r_m_values_km=default_rm_values(),
        sides=["trailing", "leading"],
        trajectory_dt_integrate_s=900.0,
        coarse_step_days=0.5,
        refine_step_s=600.0,
        nominal_window_half_width_days=160.0,
        fallback_window_half_width_days=340.0,
    )
    print(f"refine t0 count = {len(refine_cfg.t0_values)}")
    refine_rows = _run_grid(body_data, refine_cfg, max_workers=max(1, int(args.max_workers)))

    dedup: dict[tuple, dict] = {}
    for row in coarse_rows + refine_rows:
        key = (row["t0_mjd"], row["side"], row["r_m_km"])
        prev = dedup.get(key)
        if prev is None or _candidate_rank(row) < _candidate_rank(prev):
            dedup[key] = row
    rows = sorted(dedup.values(), key=_candidate_rank)

    summary = summarize_legal_window_results(rows)
    payload = {
        "task": "M5 legal 2026 window search",
        "launch_window": [MISSION_LAUNCH_START_DATE, MISSION_LAUNCH_END_DATE],
        "coarse_search": {
            "t0_step_days": args.coarse_step_days,
            "evaluated_rows": len(coarse_rows),
            "trajectory_dt_integrate_s": coarse_cfg.trajectory_dt_integrate_s,
            "event_coarse_step_days": coarse_cfg.coarse_step_days,
        },
        "refine_search": {
            "seed_t0_values": sorted(set(seed_t0)),
            "refined_t0_values": refine_t0,
            "evaluated_rows": len(refine_rows),
            "trajectory_dt_integrate_s": refine_cfg.trajectory_dt_integrate_s,
            "event_coarse_step_days": refine_cfg.coarse_step_days,
        },
        "search_runtime_sec": round(time.time() - started_total, 3),
        "max_workers": int(args.max_workers),
        **summary,
        "classification": "LEGAL_WINDOW_COARSE_PLUS_LOCAL_REFINE",
        "full_year_fine_search_pending": True,
        "search_rows": rows,
    }

    RESULTS.mkdir(parents=True, exist_ok=True)
    json_path = Path(args.output)
    csv_path = RESULTS / "m5_legal_window_search.csv"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved: {json_path}")
    print(f"Saved: {csv_path}")
    print(f"valid_lunar_returns = {summary['valid_lunar_returns']}")
    print(f"valid_fair_returns = {summary['valid_fair_returns']}")
    if summary["best_lunar_candidate"] is not None:
        best = summary["best_lunar_candidate"]
        print(
            f"best legal lunar anchor: t0={best['t0_mjd']} ({best['t0_date']}), "
            f"side={best['side']}, r_m={best['r_m_km']}, total={best['total_vinf_basis_kms']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
