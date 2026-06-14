"""
m6_complete_return_window_search.py
===================================
High-accuracy M6 complete-return launch-window search, ready for later execution.

Goals:
  - keep formal Earth-return semantics,
  - default to legal 2026 launch-window provenance,
  - support both derived-from-M5-legal and independent parameter search modes,
  - avoid silently falling back to old 61037-era local-refine imports.
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

from mission_constraints import MISSION_LAUNCH_END_DATE, MISSION_LAUNCH_START_DATE

from experiments.legal_window_search_tools import (
    SearchConfig,
    default_rm_values,
    evaluate_lunar_candidate,
    legal_coarse_t0_values,
    legal_refine_t0_values,
)
from horizons import fetch_sem_vectors


RESULTS = _REPO / "data" / "results"
M5_LEGAL_WINDOW_JSON = RESULTS / "m5_legal_window_search.json"


def _candidate_classification(valid_return_event: bool, fair: bool) -> str:
    if valid_return_event and fair:
        return "ACTUAL_RESULT"
    return "NEAR_MISS"


def _sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        0 if row.get("fair") else 1,
        0 if row.get("valid_return_event") else 1,
        float(row.get("total_vinf_basis_kms")) if row.get("total_vinf_basis_kms") is not None else float("inf"),
        float(row.get("distance_to_earth_km")) if row.get("distance_to_earth_km") is not None else float("inf"),
        float(row.get("perihelion_error_AU")) if row.get("perihelion_error_AU") is not None else float("inf"),
    )


def _search_output(
    rows: list[dict[str, Any]],
    *,
    mode: str,
    source_file: str,
    source_grid_reused: bool,
    independent_m6_search: bool,
    m6_interpretation: str,
    search_space: dict[str, Any],
    source_note: str,
) -> dict[str, Any]:
    valid_rows = [row for row in rows if row.get("valid_return_event")]
    fair_rows = [row for row in rows if row.get("fair")]
    near_miss_rows = [row for row in rows if row.get("classification") != "ACTUAL_RESULT"]
    t0_values = sorted({float(row["t0_mjd"]) for row in rows}) if rows else []

    best_valid = min(fair_rows, key=_sort_key) if fair_rows else None
    best_near_miss = min(near_miss_rows, key=_sort_key) if near_miss_rows else None
    per_t0_valid_count = {
        str(int(round(t0)) if abs(t0 - round(t0)) < 1e-9 else t0): sum(
            1 for row in fair_rows if abs(float(row["t0_mjd"]) - t0) < 1e-9
        )
        for t0 in t0_values
    }

    if best_valid is not None:
        classification = (
            "ACTUAL_RESULT_M5_DERIVED_LEGAL_WINDOW"
            if source_grid_reused
            else "ACTUAL_RESULT_LEGAL_WINDOW"
        )
        status = "valid_complete_return_found"
    else:
        classification = "FINITE_SEARCH_NEG"
        status = "finite_search_negative"

    return {
        "task": "M6 complete-return window search",
        "classification": classification,
        "status": status,
        "budget_basis": "vinf_basis",
        "candidate_source": mode,
        "source_file": source_file,
        "source_grid_reused": source_grid_reused,
        "independent_m6_search": independent_m6_search,
        "m6_interpretation": m6_interpretation,
        "launch_window": [MISSION_LAUNCH_START_DATE, MISSION_LAUNCH_END_DATE],
        "search_window_mjd": [min(t0_values), max(t0_values)] if t0_values else None,
        "t0_values": t0_values,
        "rm_values_km": sorted({float(row["r_m_km"]) for row in rows}) if rows else [],
        "side_values": sorted({str(row["side"]) for row in rows}) if rows else [],
        "search_space": search_space,
        "total_candidates_evaluated": len(rows),
        "valid_complete_return_count": len(valid_rows),
        "valid_fair_return_count": len(fair_rows),
        "best_valid_candidate": best_valid,
        "best_near_miss": best_near_miss,
        "per_t0_valid_count": per_t0_valid_count,
        "finite_search_coverage": {
            "t0_samples": len(t0_values),
            "r_m_samples": len({row["r_m_km"] for row in rows}) if rows else 0,
            "side_samples": len({row["side"] for row in rows}) if rows else 0,
            "parameterization": ["t0_mjd", "r_m_km", "side"],
            "note": "Finite search only; any negative result is finite-search negative, not impossibility.",
        },
        "event_semantics": {
            "return_vinf_defined_only_at_earth_return": True,
            "earth_return_threshold_km": search_space.get("earth_return_threshold_km"),
        },
        "event_semantics_label": "Earth-return event required",
        "not_a_legacy_perihelion_vinf_search": True,
        "source_note": source_note,
        "candidates": rows,
    }


def _legal_candidate_from_m5_row(row: dict[str, Any], idx: int) -> dict[str, Any]:
    valid = bool(row.get("valid_return_event"))
    fair = bool(row.get("fair"))
    total = row.get("total_vinf_basis_kms")
    total = round(float(total), 4) if total is not None else None
    ret = row.get("return_vinf_kms")
    ret = round(float(ret), 4) if ret is not None else None
    return {
        "candidate_id": f"m6_legal_from_m5_{idx}",
        "t0_mjd": float(row["t0_mjd"]),
        "t0_date": row.get("t0_date"),
        "side": str(row["side"]),
        "r_m_km": round(float(row["r_m_km"]), 1),
        "source_file": "data/results/m5_legal_window_search.json",
        "departure_vinf_kms": round(float(row["departure_vinf_kms"]), 4),
        "perihelion_AU": round(float(row["perihelion_AU"]), 6),
        "perihelion_error_AU": round(float(row["perihelion_error_AU"]), 6),
        "legacy_return_vinf_kms": None,
        "valid_return_event": valid,
        "distance_to_earth_km": row.get("distance_to_earth_km"),
        "distance_to_moon_km": row.get("distance_to_moon_km"),
        "return_event_mjd": row.get("return_event_mjd"),
        "return_vinf_kms": ret,
        "total_vinf_basis_kms": total,
        "fair": fair,
        "classification": _candidate_classification(valid, fair),
        "reason": (
            "imported verified legal-window complete-return candidate from M5 legal window search"
            if valid
            else str(row.get("event_reason") or "imported legal-window near miss")
        ),
        "used_nominal_window": row.get("used_nominal_window"),
        "fallback_full_window_used": row.get("fallback_full_window_used"),
    }


def _derived_legal_window_from_m5() -> dict[str, Any]:
    if not M5_LEGAL_WINDOW_JSON.exists():
        raise FileNotFoundError(
            "data/results/m5_legal_window_search.json missing; run M5 legal search first or use --mode independent-legal-window"
        )
    data = json.loads(M5_LEGAL_WINDOW_JSON.read_text(encoding="utf-8"))
    rows_in = data.get("search_rows", [])
    rows = [_legal_candidate_from_m5_row(row, idx) for idx, row in enumerate(rows_in, start=1)]
    search_space = {
        "source": "reused_verified_m5_legal_window_search",
        "launch_window": data.get("launch_window"),
        "coarse_search": data.get("coarse_search"),
        "refine_search": data.get("refine_search"),
        "earth_return_threshold_km": 1.5e6,
        "perihelion_target_AU": 0.3,
        "perihelion_tolerance_AU": 0.03,
        "return_vinf_brake_threshold_kms": 15.0,
    }
    return _search_output(
        rows,
        mode="m5_legal_window_search_grid",
        source_file="data/results/m5_legal_window_search.json",
        source_grid_reused=True,
        independent_m6_search=False,
        m6_interpretation="launch-window extraction from legal-window complete-return lunar search",
        search_space=search_space,
        source_note="M6 legal-window result derived from the verified M5 legal complete-return search rows.",
    )


def _independent_direct_search(args: argparse.Namespace) -> dict[str, Any]:
    body_data = fetch_sem_vectors(use_cache=True)
    coarse_cfg = SearchConfig(
        t0_values=legal_coarse_t0_values(args.t0_step_days),
        r_m_values_km=default_rm_values(),
        sides=["trailing", "leading"],
        target_rp_au=args.target_rp_au,
        peri_tol_au=args.peri_tol_au,
        earth_return_threshold_km=args.earth_return_threshold_km,
        return_brake_threshold_kms=args.return_brake_threshold_kms,
        nominal_window_half_width_days=args.nominal_window_half_width_days,
        fallback_window_half_width_days=args.fallback_window_half_width_days,
        coarse_step_days=args.coarse_step_days,
        coarse_dt_internal_s=args.coarse_dt_internal_s,
        refine_step_s=args.refine_step_s,
        max_extra_days=args.max_extra_days,
        trajectory_dt_integrate_s=args.trajectory_dt_integrate_s,
    )

    coarse_rows = []
    total = len(coarse_cfg.t0_values) * len(coarse_cfg.r_m_values_km) * len(coarse_cfg.sides)
    done = 0
    started = time.perf_counter()
    for t0 in coarse_cfg.t0_values:
        for side in coarse_cfg.sides:
            for r_m_km in coarse_cfg.r_m_values_km:
                done += 1
                row = evaluate_lunar_candidate(body_data, t0, side, r_m_km, config=coarse_cfg)
                row["candidate_id"] = f"m6_indep_coarse_{done}"
                row["source_file"] = "data/results/m6_complete_return_window_search.json"
                row["legacy_return_vinf_kms"] = None
                row["reason"] = row.pop("event_reason")
                coarse_rows.append(row)
                if done % 25 == 0 or done == total:
                    print(f"  progress {done}/{total} ({time.perf_counter()-started:.0f}s)")

    seed_t0 = [row["t0_mjd"] for row in sorted(coarse_rows, key=_sort_key)[: max(1, args.top_k_seeds)]]
    refine_t0 = legal_refine_t0_values(seed_t0, offsets_days=[-3, -2, -1, -0.5, 0, 0.5, 1, 2, 3])
    refine_cfg = SearchConfig(
        t0_values=refine_t0,
        r_m_values_km=default_rm_values(),
        sides=["trailing", "leading"],
        target_rp_au=args.target_rp_au,
        peri_tol_au=args.peri_tol_au,
        earth_return_threshold_km=args.earth_return_threshold_km,
        return_brake_threshold_kms=args.return_brake_threshold_kms,
        nominal_window_half_width_days=args.refine_nominal_window_half_width_days,
        fallback_window_half_width_days=args.refine_fallback_window_half_width_days,
        coarse_step_days=args.refine_coarse_step_days,
        coarse_dt_internal_s=args.refine_coarse_dt_internal_s,
        refine_step_s=args.refine_refine_step_s,
        max_extra_days=args.max_extra_days,
        trajectory_dt_integrate_s=args.refine_trajectory_dt_integrate_s,
    )

    refine_rows = []
    total_refine = len(refine_cfg.t0_values) * len(refine_cfg.r_m_values_km) * len(refine_cfg.sides)
    done_refine = 0
    started_refine = time.perf_counter()
    for t0 in refine_cfg.t0_values:
        for side in refine_cfg.sides:
            for r_m_km in refine_cfg.r_m_values_km:
                done_refine += 1
                row = evaluate_lunar_candidate(body_data, t0, side, r_m_km, config=refine_cfg)
                row["candidate_id"] = f"m6_indep_refine_{done_refine}"
                row["source_file"] = "data/results/m6_complete_return_window_search.json"
                row["legacy_return_vinf_kms"] = None
                row["reason"] = row.pop("event_reason")
                refine_rows.append(row)
                if done_refine % 25 == 0 or done_refine == total_refine:
                    print(f"  refine progress {done_refine}/{total_refine} ({time.perf_counter()-started_refine:.0f}s)")

    dedup: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in coarse_rows + refine_rows:
        key = (float(row["t0_mjd"]), str(row["side"]), float(row["r_m_km"]))
        prev = dedup.get(key)
        if prev is None or _sort_key(row) < _sort_key(prev):
            dedup[key] = row
    rows = sorted(dedup.values(), key=_sort_key)
    search_space = {
        "source": "direct_independent_legal_window_search",
        "launch_window": [MISSION_LAUNCH_START_DATE, MISSION_LAUNCH_END_DATE],
        "coarse_t0_step_days": args.t0_step_days,
        "top_k_seed_t0": args.top_k_seeds,
        "refined_t0_values": refine_t0,
        "r_m_values_km": default_rm_values(),
        "sides": ["trailing", "leading"],
        "earth_return_threshold_km": args.earth_return_threshold_km,
        "perihelion_target_AU": args.target_rp_au,
        "perihelion_tolerance_AU": args.peri_tol_au,
        "return_vinf_brake_threshold_kms": args.return_brake_threshold_kms,
        "coarse_trajectory_dt_integrate_s": args.trajectory_dt_integrate_s,
        "coarse_event_coarse_step_days": args.coarse_step_days,
        "coarse_event_refine_step_s": args.refine_step_s,
        "refine_trajectory_dt_integrate_s": args.refine_trajectory_dt_integrate_s,
        "refine_event_coarse_step_days": args.refine_coarse_step_days,
        "refine_event_refine_step_s": args.refine_refine_step_s,
        "max_extra_days": args.max_extra_days,
    }
    return _search_output(
        rows,
        mode="direct_parameter_search_legal_window",
        source_file="data/results/m6_complete_return_window_search.json",
        source_grid_reused=False,
        independent_m6_search=True,
        m6_interpretation="independent complete-return launch-window search over legal 2026 dates",
        search_space=search_space,
        source_note="Independent M6 legal-window search generated directly from parameters, not from M5 row import.",
    )


def _write_outputs(payload: dict[str, Any], output_json: Path, output_csv: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    rows = payload.get("candidates", [])
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["derived-legal-window", "independent-legal-window"],
        default="derived-legal-window",
    )
    parser.add_argument("--output", type=str, default=str(RESULTS / "m6_complete_return_window_search.json"))
    parser.add_argument("--csv-output", type=str, default=str(RESULTS / "m6_complete_return_window_search.csv"))
    parser.add_argument("--t0-step-days", type=int, default=7)
    parser.add_argument("--top-k-seeds", type=int, default=8)
    parser.add_argument("--target-rp-au", type=float, default=0.3)
    parser.add_argument("--peri-tol-au", type=float, default=0.03)
    parser.add_argument("--earth-return-threshold-km", type=float, default=1.5e6)
    parser.add_argument("--return-vinf-brake-threshold-kms", type=float, default=15.0)
    parser.add_argument("--trajectory-dt-integrate-s", type=float, default=1800.0)
    parser.add_argument("--coarse-step-days", type=float, default=0.5)
    parser.add_argument("--coarse-dt-internal-s", type=float, default=3600.0)
    parser.add_argument("--refine-step-s", type=float, default=600.0)
    parser.add_argument("--nominal-window-half-width-days", type=float, default=150.0)
    parser.add_argument("--fallback-window-half-width-days", type=float, default=320.0)
    parser.add_argument("--refine-trajectory-dt-integrate-s", type=float, default=900.0)
    parser.add_argument("--refine-coarse-step-days", type=float, default=0.25)
    parser.add_argument("--refine-coarse-dt-internal-s", type=float, default=1800.0)
    parser.add_argument("--refine-refine-step-s", type=float, default=300.0)
    parser.add_argument("--refine-nominal-window-half-width-days", type=float, default=180.0)
    parser.add_argument("--refine-fallback-window-half-width-days", type=float, default=360.0)
    parser.add_argument("--max-extra-days", type=float, default=500.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print("=" * 66)
    print("M6 complete-return window search")
    print("=" * 66)
    print(f"mode = {args.mode}")

    if args.mode == "derived-legal-window":
        payload = _derived_legal_window_from_m5()
    else:
        payload = _independent_direct_search(args)

    output_json = Path(args.output)
    output_csv = Path(args.csv_output)
    _write_outputs(payload, output_json, output_csv)

    print(f"Saved: {output_json}")
    print(f"Saved: {output_csv}")
    print(f"classification = {payload['classification']}")
    print(f"candidates evaluated = {payload['total_candidates_evaluated']}")
    print(f"valid complete returns = {payload['valid_complete_return_count']}")
    print(f"valid fair returns = {payload['valid_fair_return_count']}")
    if payload.get("best_valid_candidate"):
        best = payload["best_valid_candidate"]
        print(
            f"best valid: t0={best['t0_mjd']} side={best['side']} "
            f"r_m={best['r_m_km']} total={best['total_vinf_basis_kms']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
