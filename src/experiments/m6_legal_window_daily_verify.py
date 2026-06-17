"""
m6_legal_window_daily_verify.py
===============================
High-accuracy independent verification for the strongest candidates extracted
from the M5 daily legal-window scan.

This is still a finite verification layer, but it is materially stronger than
relabeling stored M5 rows:
  - seeds come from the daily scan,
  - every verified row is recomputed from parameters,
  - provenance is explicit about being seeded rather than fully blind.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(_REPO / "src"))

from budget_tools import best_lunar_candidate, ensure_lunar_row_formal_fields, lunar_candidate_sort_key
from horizons import fetch_sem_vectors
from mission_constraints import MISSION_LAUNCH_END_DATE, MISSION_LAUNCH_START_DATE

from experiments.legal_window_search_tools import SearchConfig, evaluate_lunar_candidate
from experiments.progress_resume import JsonlCheckpoint, ProgressBar


RESULTS = _REPO / "data" / "results"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _job_key(row: dict[str, Any]) -> str:
    return f"{float(row['t0_mjd']):.6f}|{str(row['side'])}|{float(row['r_m_km']):.3f}"


def _select_seed_rows(
    rows: list[dict[str, Any]],
    *,
    top_k_candidates: int,
    top_k_days: int,
    include_near_miss_days: int,
) -> list[dict[str, Any]]:
    normalized = [ensure_lunar_row_formal_fields(row) for row in rows]
    ranked = sorted(normalized, key=lunar_candidate_sort_key)
    selected: dict[str, dict[str, Any]] = {}

    for row in ranked[: max(1, top_k_candidates)]:
        selected[_job_key(row)] = row

    best_by_day: dict[float, dict[str, Any]] = {}
    for row in ranked:
        t0 = float(row["t0_mjd"])
        prev = best_by_day.get(t0)
        if prev is None or lunar_candidate_sort_key(row) < lunar_candidate_sort_key(prev):
            best_by_day[t0] = row
    daily_ranked = sorted(best_by_day.values(), key=lunar_candidate_sort_key)

    for row in daily_ranked[: max(1, top_k_days)]:
        selected[_job_key(row)] = row

    near_miss_days = 0
    for row in daily_ranked:
        if row.get("fair"):
            continue
        selected[_job_key(row)] = row
        near_miss_days += 1
        if near_miss_days >= max(0, include_near_miss_days):
            break

    return sorted(selected.values(), key=lunar_candidate_sort_key)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=str, default=str(RESULTS / "m5_legal_window_daily_scan.json"))
    parser.add_argument("--output", type=str, default=str(RESULTS / "m6_legal_window_daily_verify.json"))
    parser.add_argument("--csv-output", type=str, default=str(RESULTS / "m6_legal_window_daily_verify.csv"))
    parser.add_argument("--checkpoint-jsonl", type=str, default=str(RESULTS / "m6_legal_window_daily_verify.resume.jsonl"))
    parser.add_argument("--top-k-candidates", type=int, default=18)
    parser.add_argument("--top-k-days", type=int, default=24)
    parser.add_argument("--include-near-miss-days", type=int, default=6)
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print("=" * 66)
    print("M6 legal-window daily verify")
    print("=" * 66)
    started = time.time()

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"missing input daily scan JSON: {input_path}")
    source_payload = _load_json(input_path)
    source_rows = source_payload.get("search_rows", [])
    if not source_rows:
        raise ValueError("input daily scan JSON contains no search_rows")

    seed_rows = _select_seed_rows(
        source_rows,
        top_k_candidates=int(args.top_k_candidates),
        top_k_days=int(args.top_k_days),
        include_near_miss_days=int(args.include_near_miss_days),
    )
    body_data = fetch_sem_vectors(use_cache=True)
    checkpoint = None if args.no_resume else JsonlCheckpoint(
        Path(args.checkpoint_jsonl),
        key_fn=lambda row: str(row["_checkpoint_key"]),
    )
    config = SearchConfig(
        t0_values=[],
        r_m_values_km=[],
        sides=[],
        trajectory_dt_integrate_s=450.0,
        coarse_step_days=0.25,
        coarse_dt_internal_s=900.0,
        refine_step_s=120.0,
        nominal_window_half_width_days=180.0,
        fallback_window_half_width_days=360.0,
        max_extra_days=500.0,
    )

    verified_rows: list[dict[str, Any]] = []
    pending_rows: list[dict[str, Any]] = []
    for row in seed_rows:
        key = _job_key(row)
        if checkpoint is not None and checkpoint.has_key(key):
            cached = dict(checkpoint.rows_by_key[key])
            cached.pop("_checkpoint_key", None)
            verified_rows.append(cached)
        else:
            pending_rows.append(row)

    progress = ProgressBar(len(seed_rows), label="m6-daily-verify")
    progress.update(len(verified_rows), extra=f"resume={len(verified_rows)}")

    for idx, seed in enumerate(pending_rows, start=1):
        row = evaluate_lunar_candidate(
            body_data,
            float(seed["t0_mjd"]),
            str(seed["side"]),
            float(seed["r_m_km"]),
            config=config,
        )
        row["candidate_id"] = f"m6_daily_verify_{len(verified_rows) + 1}"
        row["source_file"] = str(input_path.relative_to(_REPO)).replace("\\", "/")
        row["seeded_from_daily_scan"] = True
        row["seed_rank_origin"] = "top_daily_scan_candidate"
        row["verify_runtime_hint"] = "recomputed_from_parameters"
        row["reason"] = row.pop("event_reason")
        verified_rows.append(row)
        if checkpoint is not None:
            checkpoint.append({**row, "_checkpoint_key": _job_key(seed)})
        progress.update(len(verified_rows), extra=f"pending_done={idx}/{len(pending_rows)}")
    progress.finish()

    verified_rows = sorted(
        [ensure_lunar_row_formal_fields(row) for row in verified_rows],
        key=lunar_candidate_sort_key,
    )
    valid_rows = [row for row in verified_rows if row.get("valid_return_event")]
    fair_rows = [row for row in verified_rows if row.get("fair")]
    near_miss_rows = [row for row in verified_rows if not row.get("fair")]
    best_valid = best_lunar_candidate(verified_rows, fair_only=True)
    best_near_miss = min(near_miss_rows, key=lunar_candidate_sort_key) if near_miss_rows else None

    per_t0_valid_count: dict[str, int] = {}
    for row in fair_rows:
        t0 = float(row["t0_mjd"])
        key = str(int(round(t0)) if abs(t0 - round(t0)) < 1e-9 else t0)
        per_t0_valid_count[key] = per_t0_valid_count.get(key, 0) + 1

    payload = {
        "task": "M6 legal-window daily verify",
        "classification": (
            "ACTUAL_RESULT_DAILY_VERIFIED_LEGAL_WINDOW"
            if best_valid is not None
            else "FINITE_SEARCH_NEG"
        ),
        "status": "valid_verified_candidate_found" if best_valid is not None else "finite_search_negative",
        "budget_basis": "three_segment_formal",
        "supplementary_budget_basis": "vinf_basis",
        "candidate_source": "m5_legal_window_daily_scan_seeded_verify",
        "source_file": str(input_path.relative_to(_REPO)).replace("\\", "/"),
        "seeded_from_m5_daily_scan": True,
        "source_grid_reused": False,
        "independent_m6_search": True,
        "m6_interpretation": "high-accuracy independent verification of top candidates from the legal daily scan",
        "launch_window": [MISSION_LAUNCH_START_DATE, MISSION_LAUNCH_END_DATE],
        "search_space": {
            "seed_selection": {
                "top_k_candidates": int(args.top_k_candidates),
                "top_k_days": int(args.top_k_days),
                "include_near_miss_days": int(args.include_near_miss_days),
            },
            "verification_config": {
                "trajectory_dt_integrate_s": config.trajectory_dt_integrate_s,
                "event_coarse_step_days": config.coarse_step_days,
                "event_coarse_dt_internal_s": config.coarse_dt_internal_s,
                "event_refine_step_s": config.refine_step_s,
                "nominal_window_half_width_days": config.nominal_window_half_width_days,
                "fallback_window_half_width_days": config.fallback_window_half_width_days,
                "earth_return_threshold_km": config.earth_return_threshold_km,
                "perihelion_target_AU": config.target_rp_au,
                "perihelion_tolerance_AU": config.peri_tol_au,
                "return_vinf_brake_threshold_kms": config.return_brake_threshold_kms,
            },
        },
        "search_runtime_sec": round(time.time() - started, 3),
        "resume_enabled": checkpoint is not None,
        "checkpoint_jsonl": None if checkpoint is None else str(Path(args.checkpoint_jsonl).relative_to(_REPO)).replace("\\", "/"),
        "selected_seed_count": len(seed_rows),
        "total_candidates_evaluated": len(verified_rows),
        "valid_complete_return_count": len(valid_rows),
        "valid_fair_return_count": len(fair_rows),
        "best_valid_candidate": best_valid,
        "best_verified_candidate": best_valid,
        "best_near_miss": best_near_miss,
        "per_t0_valid_count": dict(sorted(per_t0_valid_count.items())),
        "event_semantics": {
            "return_vinf_defined_only_at_earth_return": True,
            "earth_return_threshold_km": config.earth_return_threshold_km,
        },
        "not_a_legacy_perihelion_vinf_search": True,
        "verified_candidates": verified_rows,
        "seed_rows": seed_rows,
        "source_scan_classification": source_payload.get("classification"),
    }

    output_json = Path(args.output)
    output_csv = Path(args.csv_output)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(verified_rows[0].keys()))
        writer.writeheader()
        writer.writerows(verified_rows)

    print(f"Saved: {output_json}")
    print(f"Saved: {output_csv}")
    print(f"classification = {payload['classification']}")
    print(f"selected_seed_count = {len(seed_rows)}")
    print(f"valid complete returns = {len(valid_rows)}")
    print(f"valid fair returns = {len(fair_rows)}")
    if best_valid is not None:
        print(
            f"best verified: t0={best_valid['t0_mjd']} side={best_valid['side']} "
            f"r_m={best_valid['r_m_km']} dv_total={best_valid.get('dv_total_kms')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
