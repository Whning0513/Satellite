"""
m6_independent_window_search.py
===============================
Independent M6 launch-window search that does not read the M5 local refine grid.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
RESULTS = REPO / "data" / "results"
sys.path.insert(0, str(SRC))

from constants import AU_KM, DT_MAIN, R_MOON
from horizons import fetch_sem_vectors
from trajectory import DesignParams, solve_trajectory

from experiments.return_search_tools import search_best_return_event


T0_VALUES = list(range(61025, 61056, 3))
R_M_VALUES_KM = [R_MOON + d for d in [100.0, 500.0, 1000.0, 2000.0, 3000.0, 5000.0, 8000.0]]
SIDES = ["trailing", "leading"]
TARGET_RP_AU = 0.3
PERI_TOL_AU = 0.03
RETURN_BRAKE_THRESHOLD_KMS = 15.0
EARTH_RETURN_THRESHOLD_KM = 1.5e6
NOMINAL_RETURN_MJD = 61404.87


def _classification(valid_return: bool, fair: bool) -> str:
    if valid_return and fair:
        return "ACTUAL_RESULT"
    return "NEAR_MISS"


def main() -> int:
    body_data = fetch_sem_vectors(use_cache=True)
    rows: list[dict[str, Any]] = []
    t_all = time.perf_counter()
    total = len(T0_VALUES) * len(R_M_VALUES_KM) * len(SIDES)
    done = 0

    for t0_mjd in T0_VALUES:
        for side in SIDES:
            for r_m_km in R_M_VALUES_KM:
                done += 1
                traj = solve_trajectory(
                    DesignParams(t0_mjd=float(t0_mjd), r_m=float(r_m_km), side=side, r_p=TARGET_RP_AU * AU_KM),
                    body_data=body_data,
                    dt_integrate=DT_MAIN,
                    verbose=False,
                )
                event = search_best_return_event(
                    traj=traj,
                    body_data=body_data,
                    launch_mjd=float(t0_mjd),
                    nominal_return_mjd=NOMINAL_RETURN_MJD,
                    threshold_km=EARTH_RETURN_THRESHOLD_KM,
                    nominal_window_half_width_days=60.0,
                    fallback_window_half_width_days=240.0,
                )
                perihelion_au = round(float(traj.r_p_achieved_km) / AU_KM, 6)
                peri_err_au = round(abs(perihelion_au - TARGET_RP_AU), 6)
                dep_vinf = round(float(traj.v_inf_earth), 4)
                ret_vinf = event["return_vinf_kms"]
                total_vinf = (
                    round(dep_vinf + max(0.0, float(ret_vinf) - RETURN_BRAKE_THRESHOLD_KMS), 4)
                    if ret_vinf is not None
                    else None
                )
                fair = bool(
                    event["valid_return_event"]
                    and peri_err_au <= PERI_TOL_AU
                    and ret_vinf is not None
                    and float(ret_vinf) <= RETURN_BRAKE_THRESHOLD_KMS
                )
                rows.append(
                    {
                        "candidate_id": f"m6_independent_t0_{t0_mjd}_{side}_rm_{int(round(r_m_km))}",
                        "t0_mjd": float(t0_mjd),
                        "side": side,
                        "r_m_km": round(float(r_m_km), 1),
                        "departure_vinf_kms": dep_vinf,
                        "perihelion_AU": perihelion_au,
                        "perihelion_error_AU": peri_err_au,
                        "valid_return_event": bool(event["valid_return_event"]),
                        "distance_to_earth_km": event["event_distance_km"],
                        "distance_to_moon_km": event["distance_to_moon_km"],
                        "return_event_mjd": event["return_event_mjd"],
                        "return_vinf_kms": ret_vinf,
                        "total_vinf_basis_kms": total_vinf,
                        "fair": fair,
                        "classification": _classification(bool(event["valid_return_event"]), fair),
                        "used_nominal_window": event["used_nominal_window"],
                        "fallback_full_window_used": event["fallback_full_window_used"],
                        "reason": (
                            "independent valid complete-return candidate"
                            if fair
                            else event["event_reason"] or "fails fair-mission constraints"
                        ),
                    }
                )
                print(f"[{done}/{total}] t0={t0_mjd} side={side} r_m={r_m_km:.1f}")

    valid_rows = [row for row in rows if row["valid_return_event"]]
    fair_rows = [row for row in rows if row["fair"]]
    near_miss_rows = [row for row in rows if row["classification"] != "ACTUAL_RESULT"]
    best_valid = min(fair_rows, key=lambda row: (row["total_vinf_basis_kms"], row["distance_to_earth_km"])) if fair_rows else None
    best_near_miss = min(
        near_miss_rows,
        key=lambda row: (
            float("inf") if row["distance_to_earth_km"] is None else row["distance_to_earth_km"],
            float("inf") if row["perihelion_error_AU"] is None else row["perihelion_error_AU"],
        ),
    ) if near_miss_rows else None

    payload = {
        "task": "M6 independent launch-window search",
        "independent_m6_search": True,
        "candidate_source": "direct_parameter_search",
        "source_grid_reused": False,
        "search_space": {
            "t0_mjd_range": [T0_VALUES[0], T0_VALUES[-1]],
            "t0_step_days": 3,
            "r_m_km_range": [round(R_M_VALUES_KM[0], 1), round(R_M_VALUES_KM[-1], 1)],
            "r_m_count": len(R_M_VALUES_KM),
            "sides": SIDES,
            "nominal_return_window_half_width_days": 60.0,
            "earth_return_threshold_km": EARTH_RETURN_THRESHOLD_KM,
            "perihelion_target_AU": TARGET_RP_AU,
            "perihelion_tolerance_AU": PERI_TOL_AU,
            "return_vinf_brake_threshold_kms": RETURN_BRAKE_THRESHOLD_KMS,
        },
        "candidates_evaluated": len(rows),
        "valid_complete_returns": len(valid_rows),
        "valid_fair_returns": len(fair_rows),
        "best_valid_candidate": best_valid,
        "best_near_miss": best_near_miss,
        "classification": "ACTUAL_RESULT_INDEPENDENT_WINDOW" if best_valid is not None else "FINITE_SEARCH_NEG",
        "runtime_sec": round(time.perf_counter() - t_all, 3),
        "coverage_note": "Independent finite search only; negative results remain finite-search negatives, not impossibility claims.",
        "candidates": rows,
    }

    json_path = RESULTS / "m6_independent_window_search.json"
    csv_path = RESULTS / "m6_independent_window_search.csv"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved: {json_path}")
    print(f"Saved: {csv_path}")
    print(f"candidates_evaluated = {len(rows)}")
    print(f"valid_complete_returns = {len(valid_rows)}")
    print(f"valid_fair_returns = {len(fair_rows)}")
    print(f"classification = {payload['classification']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
