"""
m5_m6_sensitivity_scan.py
=========================
Sensitivity scan around the current best lunar Earth-return candidate.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
RESULTS = REPO / "data" / "results"
sys.path.insert(0, str(SRC))

from constants import AU_KM, DT_MAIN
from horizons import fetch_sem_vectors
from trajectory import DesignParams, solve_trajectory

from experiments.return_search_tools import search_best_return_event


BEST_T0 = 61037.0
BEST_SIDE = "trailing"
BEST_RM_KM = 1837.4
BEST_RETURN_MJD = 61404.87
TARGET_RP_AU = 0.3
RETURN_BRAKE_THRESHOLD_KMS = 15.0

T0_OFFSETS_DAYS = [-1.0, -0.5, 0.0, 0.5, 1.0]
RM_OFFSETS_KM = [-50.0, 0.0, 50.0, 100.0, 200.0]
DT_OPTIONS = {
    "half": DT_MAIN / 2.0,
    "baseline": DT_MAIN,
    "double": DT_MAIN * 2.0,
}
EARTH_THRESHOLDS_KM = [1.0e6, 1.5e6, 2.0e6]
PERI_TOLS_AU = [0.02, 0.03, 0.04]


def _load_json(name: str) -> dict[str, Any] | None:
    path = RESULTS / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _stats(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    arr = np.asarray(values, dtype=float)
    return {
        "mean": round(float(arr.mean()), 6),
        "p50": round(float(np.percentile(arr, 50)), 6),
        "p95": round(float(np.percentile(arr, 95)), 6),
    }


def _classification(fair_fraction: float) -> str:
    if fair_fraction >= 0.5:
        return "stable"
    if fair_fraction >= 0.1:
        return "sensitive"
    return "fragile"


def main() -> int:
    body_data = fetch_sem_vectors(use_cache=True)
    m5_no_lunar = _load_json("m5_no_lunar_t61037_deep_search.json")
    no_lunar_total = None
    if m5_no_lunar and m5_no_lunar.get("best_valid"):
        no_lunar_total = float(m5_no_lunar["best_valid"]["total_dv_proxy_kms"])

    physical_runs: list[dict[str, Any]] = []
    eval_rows: list[dict[str, Any]] = []
    total_runs = len(T0_OFFSETS_DAYS) * len(RM_OFFSETS_KM) * len(DT_OPTIONS)
    run_idx = 0
    t_all = time.perf_counter()

    for t0_offset in T0_OFFSETS_DAYS:
        for rm_offset in RM_OFFSETS_KM:
            for dt_label, dt_value in DT_OPTIONS.items():
                run_idx += 1
                t0_mjd = BEST_T0 + t0_offset
                r_m_km = BEST_RM_KM + rm_offset
                params = DesignParams(t0_mjd=t0_mjd, r_m=r_m_km, side=BEST_SIDE, r_p=TARGET_RP_AU * AU_KM)
                traj = solve_trajectory(params, body_data, verbose=False, dt_integrate=dt_value)
                event = search_best_return_event(
                    traj=traj,
                    body_data=body_data,
                    launch_mjd=t0_mjd,
                    nominal_return_mjd=BEST_RETURN_MJD,
                    threshold_km=max(EARTH_THRESHOLDS_KM),
                    nominal_window_half_width_days=60.0,
                    fallback_window_half_width_days=180.0,
                )
                perihelion_au = round(float(traj.r_p_achieved_km) / AU_KM, 6)
                peri_err_au = abs(perihelion_au - TARGET_RP_AU)
                dep_vinf = round(float(traj.v_inf_earth), 4)
                ret_vinf = event["return_vinf_kms"]
                total_vinf = None
                if ret_vinf is not None:
                    total_vinf = round(dep_vinf + max(0.0, float(ret_vinf) - RETURN_BRAKE_THRESHOLD_KMS), 4)

                base_run = {
                    "run_id": f"scan_{run_idx}",
                    "t0_mjd": round(t0_mjd, 6),
                    "t0_offset_days": t0_offset,
                    "r_m_km": round(r_m_km, 3),
                    "r_m_offset_km": rm_offset,
                    "side": BEST_SIDE,
                    "side_perturbation_supported": False,
                    "dt_label": dt_label,
                    "dt_seconds": dt_value,
                    "perihelion_AU": perihelion_au,
                    "perihelion_error_AU": round(peri_err_au, 6),
                    "departure_vinf_kms": dep_vinf,
                    "coarse_min_distance_km": event["coarse_min_distance_km"],
                    "event_distance_km": event["event_distance_km"],
                    "distance_to_moon_km": event["distance_to_moon_km"],
                    "return_event_mjd": event["return_event_mjd"],
                    "return_vinf_kms": ret_vinf,
                    "total_vinf_basis_kms": total_vinf,
                    "used_nominal_window": event["used_nominal_window"],
                    "fallback_full_window_used": event["fallback_full_window_used"],
                    "event_reason": event["event_reason"],
                }
                physical_runs.append(base_run)

                for threshold_km in EARTH_THRESHOLDS_KM:
                    valid_return = event["event_distance_km"] is not None and event["event_distance_km"] <= threshold_km
                    for peri_tol_au in PERI_TOLS_AU:
                        fair = bool(
                            valid_return
                            and peri_err_au <= peri_tol_au
                            and ret_vinf is not None
                            and float(ret_vinf) <= RETURN_BRAKE_THRESHOLD_KMS
                        )
                        ratio = None
                        if no_lunar_total is not None and abs(t0_mjd - BEST_T0) < 1e-9 and fair and total_vinf is not None:
                            ratio = round((no_lunar_total - total_vinf) / no_lunar_total, 6)
                        eval_rows.append(
                            {
                                **base_run,
                                "earth_return_threshold_km": threshold_km,
                                "perihelion_tolerance_AU": peri_tol_au,
                                "valid_return_event": valid_return,
                                "fair": fair,
                                "saving_ratio_vs_t0_61037_no_lunar": ratio,
                            }
                        )
                print(f"[{run_idx}/{total_runs}] t0={t0_mjd:.2f}, r_m={r_m_km:.1f}, dt={dt_label}")

    valid_rows = [row for row in eval_rows if row["valid_return_event"]]
    fair_rows = [row for row in eval_rows if row["fair"]]
    baseline_rows = [
        row for row in eval_rows
        if row["dt_label"] == "baseline"
        and abs(float(row["earth_return_threshold_km"]) - 1.5e6) < 1e-9
        and abs(float(row["perihelion_tolerance_AU"]) - 0.03) < 1e-12
    ]
    baseline_fair_fraction = (
        sum(1 for row in baseline_rows if row["fair"]) / len(baseline_rows)
        if baseline_rows else 0.0
    )
    conclusion = _classification(baseline_fair_fraction)

    valid_distances = [float(row["event_distance_km"]) for row in valid_rows if row["event_distance_km"] is not None]
    valid_return_vinf = [float(row["return_vinf_kms"]) for row in valid_rows if row["return_vinf_kms"] is not None]
    valid_total = [float(row["total_vinf_basis_kms"]) for row in valid_rows if row["total_vinf_basis_kms"] is not None]
    valid_ratios = [
        float(row["saving_ratio_vs_t0_61037_no_lunar"])
        for row in fair_rows
        if row["saving_ratio_vs_t0_61037_no_lunar"] is not None
    ]

    best_valid = min(fair_rows, key=lambda row: (row["total_vinf_basis_kms"], row["event_distance_km"])) if fair_rows else None
    worst_valid = max(fair_rows, key=lambda row: (row["total_vinf_basis_kms"], row["event_distance_km"])) if fair_rows else None

    payload = {
        "task": "M5/M6 sensitivity scan",
        "reference_candidate": {
            "t0_mjd": BEST_T0,
            "side": BEST_SIDE,
            "r_m_km": BEST_RM_KM,
            "return_event_mjd": BEST_RETURN_MJD,
        },
        "tested_perturbations": {
            "t0_offsets_days": T0_OFFSETS_DAYS,
            "r_m_offsets_km": RM_OFFSETS_KM,
            "dt_options_seconds": {k: float(v) for k, v in DT_OPTIONS.items()},
            "earth_return_thresholds_km": EARTH_THRESHOLDS_KM,
            "perihelion_tolerances_AU": PERI_TOLS_AU,
            "side_perturbation": "not supported by current solver; side kept fixed at trailing",
        },
        "physical_run_count": len(physical_runs),
        "evaluation_row_count": len(eval_rows),
        "valid_return_count": len(valid_rows),
        "fair_count": len(fair_rows),
        "median_return_distance_km": round(float(np.percentile(valid_distances, 50)), 3) if valid_distances else None,
        "p95_return_distance_km": round(float(np.percentile(valid_distances, 95)), 3) if valid_distances else None,
        "return_vinf_stats_kms": _stats(valid_return_vinf),
        "total_vinf_basis_stats_kms": _stats(valid_total),
        "saving_ratio_range_vs_t0_61037_no_lunar": (
            {
                "min": round(min(valid_ratios), 6),
                "max": round(max(valid_ratios), 6),
            }
            if valid_ratios
            else None
        ),
        "baseline_setting": {
            "dt_label": "baseline",
            "earth_return_threshold_km": 1.5e6,
            "perihelion_tolerance_AU": 0.03,
            "fair_fraction": round(baseline_fair_fraction, 6),
        },
        "conclusion": conclusion,
        "best_valid_candidate": best_valid,
        "worst_valid_candidate": worst_valid,
        "runtime_sec": round(time.perf_counter() - t_all, 3),
        "rows": eval_rows,
    }

    json_path = RESULTS / "m5_m6_sensitivity_scan.json"
    csv_path = RESULTS / "m5_m6_sensitivity_scan.csv"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(eval_rows[0].keys()))
        writer.writeheader()
        writer.writerows(eval_rows)

    print(f"Saved: {json_path}")
    print(f"Saved: {csv_path}")
    print(f"physical_run_count = {len(physical_runs)}")
    print(f"valid_return_count = {len(valid_rows)}")
    print(f"fair_count = {len(fair_rows)}")
    print(f"conclusion = {conclusion}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
