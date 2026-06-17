"""
m5_legal_window_daily_scan.py
=============================
Daily-coverage legal 2026 launch-window scan for Rule 19 style verification.

This is the stronger annual-search path:
  - every legal launch day in 2026 is sampled,
  - each day is evaluated over the same real Moon phase / real return search
    semantics as the main M5/M6 workflow,
  - optional local refinement densifies top candidate days without claiming a
    continuous-space proof.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(_REPO / "src"))

from horizons import fetch_sem_vectors
from mission_constraints import (
    MISSION_LAUNCH_END_DATE,
    MISSION_LAUNCH_END_MJD,
    MISSION_LAUNCH_START_DATE,
    MISSION_LAUNCH_START_MJD,
)

from experiments.legal_window_search_tools import (
    SearchConfig,
    default_rm_values,
    legal_refine_t0_values,
    summarize_legal_window_results,
)
from experiments.m5_legal_window_search import (
    RESULTS,
    _candidate_rank,
    _parse_float_list,
    _parse_side_list,
    _run_grid,
)
from experiments.progress_resume import JsonlCheckpoint


def _daily_t0_values() -> list[float]:
    return [float(x) for x in range(int(MISSION_LAUNCH_START_MJD), int(MISSION_LAUNCH_END_MJD) + 1)]


def _best_by_t0(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[float, dict[str, Any]] = {}
    for row in rows:
        t0 = float(row["t0_mjd"])
        prev = best.get(t0)
        if prev is None or _candidate_rank(row) < _candidate_rank(prev):
            best[t0] = row
    return [best[t0] for t0 in sorted(best)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    default_workers = 1 if os.name == "nt" else 12
    parser.add_argument("--max-workers", type=int, default=default_workers)
    parser.add_argument("--top-k-seeds", type=int, default=16)
    parser.add_argument("--skip-refine", action="store_true")
    parser.add_argument("--rm-values-km", type=str, default="")
    parser.add_argument("--sides", type=str, default="trailing,leading")
    parser.add_argument("--output", type=str, default=str(RESULTS / "m5_legal_window_daily_scan.json"))
    parser.add_argument("--checkpoint-jsonl", type=str, default=str(RESULTS / "m5_legal_window_daily_scan.resume.jsonl"))
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print("=" * 66)
    print("M5 legal 2026 daily scan")
    print("=" * 66)
    started_total = time.time()
    body_data = fetch_sem_vectors(use_cache=True)
    checkpoint = None if args.no_resume else JsonlCheckpoint(
        Path(args.checkpoint_jsonl),
        key_fn=lambda row: str(row["_checkpoint_key"]),
    )

    coarse_t0_values = _daily_t0_values()
    rm_values = _parse_float_list(args.rm_values_km) if args.rm_values_km else default_rm_values()
    side_values = _parse_side_list(args.sides)

    coarse_cfg = SearchConfig(
        t0_values=coarse_t0_values,
        r_m_values_km=rm_values,
        sides=side_values,
        trajectory_dt_integrate_s=1800.0,
        coarse_step_days=0.5,
        refine_step_s=600.0,
        nominal_window_half_width_days=150.0,
        fallback_window_half_width_days=320.0,
    )
    print(f"daily coarse t0 count = {len(coarse_cfg.t0_values)}")
    coarse_rows = _run_grid(
        body_data,
        coarse_cfg,
        max_workers=max(1, int(args.max_workers)),
        stage="daily-coarse",
        checkpoint=checkpoint,
    )
    coarse_rows_sorted = sorted(coarse_rows, key=_candidate_rank)

    refine_rows: list[dict[str, Any]] = []
    refine_cfg = None
    if not args.skip_refine:
        seed_t0 = [row["t0_mjd"] for row in coarse_rows_sorted[: max(1, int(args.top_k_seeds))]]
        refine_t0 = legal_refine_t0_values(seed_t0, offsets_days=[-1.0, -0.5, 0.0, 0.5, 1.0])
        refine_cfg = SearchConfig(
            t0_values=refine_t0,
            r_m_values_km=rm_values,
            sides=side_values,
            trajectory_dt_integrate_s=900.0,
            coarse_step_days=0.25,
            coarse_dt_internal_s=1800.0,
            refine_step_s=300.0,
            nominal_window_half_width_days=180.0,
            fallback_window_half_width_days=360.0,
        )
        print(f"local refine t0 count = {len(refine_cfg.t0_values)}")
        refine_rows = _run_grid(
            body_data,
            refine_cfg,
            max_workers=max(1, int(args.max_workers)),
            stage="daily-refine",
            checkpoint=checkpoint,
        )
    else:
        seed_t0 = [row["t0_mjd"] for row in coarse_rows_sorted[: max(1, int(args.top_k_seeds))]]
        refine_t0 = []

    dedup: dict[tuple[float, str, float], dict[str, Any]] = {}
    for row in coarse_rows + refine_rows:
        key = (float(row["t0_mjd"]), str(row["side"]), float(row["r_m_km"]))
        prev = dedup.get(key)
        if prev is None or _candidate_rank(row) < _candidate_rank(prev):
            dedup[key] = row
    rows = sorted(dedup.values(), key=_candidate_rank)
    summary = summarize_legal_window_results(rows)
    daily_best_rows = _best_by_t0(rows)

    payload = {
        "task": "M5 legal 2026 daily scan",
        "launch_window": [MISSION_LAUNCH_START_DATE, MISSION_LAUNCH_END_DATE],
        "classification": "LEGAL_WINDOW_DAILY_SCAN",
        "full_year_daily_t0_coverage": True,
        "coarse_daily_scan": {
            "evaluated_rows": len(coarse_rows),
            "t0_values": coarse_t0_values,
            "trajectory_dt_integrate_s": coarse_cfg.trajectory_dt_integrate_s,
            "event_coarse_step_days": coarse_cfg.coarse_step_days,
        },
        "local_refine": {
            "seed_t0_values": sorted(set(seed_t0)),
            "refined_t0_values": refine_t0,
            "evaluated_rows": len(refine_rows),
            "trajectory_dt_integrate_s": refine_cfg.trajectory_dt_integrate_s if refine_cfg else None,
            "event_coarse_step_days": refine_cfg.coarse_step_days if refine_cfg else None,
            "skipped": bool(args.skip_refine),
        },
        "search_runtime_sec": round(time.time() - started_total, 3),
        "max_workers": int(args.max_workers),
        "resume_enabled": checkpoint is not None,
        "checkpoint_jsonl": None if checkpoint is None else str(Path(args.checkpoint_jsonl).relative_to(_REPO)).replace("\\", "/"),
        **summary,
        "daily_best_rows": daily_best_rows,
        "search_rows": rows,
        "coverage_note": "Every legal 2026 launch day is sampled explicitly; local refine only densifies top days.",
    }

    RESULTS.mkdir(parents=True, exist_ok=True)
    json_path = Path(args.output)
    csv_path = RESULTS / "m5_legal_window_daily_scan.csv"
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
            f"best daily legal lunar anchor: t0={best['t0_mjd']} ({best['t0_date']}), "
            f"side={best['side']}, r_m={best['r_m_km']}, dv_total={best['dv_total_kms']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
