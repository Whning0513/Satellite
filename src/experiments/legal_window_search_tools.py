"""
legal_window_search_tools.py
============================
Shared helpers for legal 2026 launch-window searches.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np

from constants import AU_KM, R_MOON
from mission_constraints import (
    MISSION_LAUNCH_END_MJD,
    MISSION_LAUNCH_START_MJD,
    mjd_to_date_str,
)
from trajectory import DesignParams, solve_trajectory

from experiments.return_search_tools import search_best_return_event


TARGET_RP_AU = 0.3
PERI_TOL_AU = 0.03
RETURN_THRESHOLD_KM = 1.5e6
RETURN_BRAKE_THRESHOLD_KMS = 15.0


@dataclass
class SearchConfig:
    t0_values: list[float]
    r_m_values_km: list[float]
    sides: list[str]
    target_rp_au: float = TARGET_RP_AU
    peri_tol_au: float = PERI_TOL_AU
    earth_return_threshold_km: float = RETURN_THRESHOLD_KM
    return_brake_threshold_kms: float = RETURN_BRAKE_THRESHOLD_KMS
    nominal_return_offset_days: float = 260.0
    nominal_window_half_width_days: float = 150.0
    fallback_window_half_width_days: float = 320.0
    coarse_step_days: float = 0.5
    coarse_dt_internal_s: float = 3600.0
    refine_step_s: float = 600.0
    max_extra_days: float = 500.0
    trajectory_dt_integrate_s: float = 1800.0


def legal_coarse_t0_values(step_days: int) -> list[float]:
    return [float(x) for x in range(int(MISSION_LAUNCH_START_MJD), int(MISSION_LAUNCH_END_MJD) + 1, int(step_days))]


def legal_refine_t0_values(seed_t0_values: Iterable[float], offsets_days: Iterable[float]) -> list[float]:
    values = set()
    for seed in seed_t0_values:
        for offset in offsets_days:
            t0 = float(seed) + float(offset)
            if MISSION_LAUNCH_START_MJD <= t0 <= MISSION_LAUNCH_END_MJD:
                values.add(round(t0, 6))
    return sorted(values)


def default_rm_values() -> list[float]:
    return [R_MOON + d for d in [100.0, 300.0, 500.0, 800.0, 1000.0, 1500.0, 2000.0, 3000.0, 5000.0, 8000.0]]


def evaluate_lunar_candidate(
    body_data: dict,
    t0_mjd: float,
    side: str,
    r_m_km: float,
    *,
    config: SearchConfig,
) -> dict[str, Any]:
    params = DesignParams(
        t0_mjd=float(t0_mjd),
        r_m=float(r_m_km),
        side=side,
        r_p=config.target_rp_au * AU_KM,
    )
    traj = solve_trajectory(
        params,
        body_data=body_data,
        dt_integrate=config.trajectory_dt_integrate_s,
        verbose=False,
    )
    nominal_return_mjd = float(t0_mjd) + float(traj.t_total_days) + config.nominal_return_offset_days
    event = search_best_return_event(
        traj=traj,
        body_data=body_data,
        launch_mjd=float(t0_mjd),
        nominal_return_mjd=nominal_return_mjd,
        threshold_km=config.earth_return_threshold_km,
        nominal_window_half_width_days=config.nominal_window_half_width_days,
        fallback_window_half_width_days=config.fallback_window_half_width_days,
        coarse_step_days=config.coarse_step_days,
        coarse_dt_internal_s=config.coarse_dt_internal_s,
        refine_step_s=config.refine_step_s,
        max_extra_days=config.max_extra_days,
    )
    peri_au = float(traj.r_p_achieved_km / AU_KM)
    peri_err = abs(peri_au - config.target_rp_au)
    dep_vinf = float(traj.v_inf_earth)
    ret_vinf = event["return_vinf_kms"]
    total_vinf_basis = (
        dep_vinf + max(0.0, float(ret_vinf) - config.return_brake_threshold_kms)
        if ret_vinf is not None
        else None
    )
    fair = bool(
        event["valid_return_event"]
        and peri_err <= config.peri_tol_au
        and ret_vinf is not None
        and float(ret_vinf) <= config.return_brake_threshold_kms
    )
    return {
        "t0_mjd": float(t0_mjd),
        "t0_date": mjd_to_date_str(float(t0_mjd)),
        "side": side,
        "r_m_km": round(float(r_m_km), 1),
        "departure_vinf_kms": round(dep_vinf, 4),
        "perihelion_AU": round(peri_au, 6),
        "perihelion_error_AU": round(peri_err, 6),
        "swingby_dv_kms": round(float(traj.swingby.dv_mag), 6) if traj.swingby else None,
        "dist_moon_min_km": round(float(traj.dist_moon_min), 1),
        "valid_return_event": bool(event["valid_return_event"]),
        "distance_to_earth_km": event["event_distance_km"],
        "distance_to_moon_km": event["distance_to_moon_km"],
        "return_event_mjd": event["return_event_mjd"],
        "return_vinf_kms": ret_vinf,
        "total_vinf_basis_kms": round(total_vinf_basis, 4) if total_vinf_basis is not None else None,
        "fair": fair,
        "used_nominal_window": event["used_nominal_window"],
        "fallback_full_window_used": event["fallback_full_window_used"],
        "event_reason": event["event_reason"],
        "t_total_days_to_perihelion": round(float(traj.t_total_days), 4),
        "classification": "ACTUAL_RESULT" if fair else "NEAR_MISS",
    }


def summarize_legal_window_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in rows if row["valid_return_event"]]
    fair = [row for row in rows if row["fair"]]
    best = min(fair, key=lambda row: (row["total_vinf_basis_kms"], row["distance_to_earth_km"])) if fair else None

    per_month_valid_counts: dict[str, int] = defaultdict(int)
    best_by_month: dict[str, dict[str, Any]] = {}
    for row in fair:
        month = row["t0_date"][:7]
        per_month_valid_counts[month] += 1
        prev = best_by_month.get(month)
        if prev is None or (
            row["total_vinf_basis_kms"],
            row["distance_to_earth_km"],
        ) < (
            prev["total_vinf_basis_kms"],
            prev["distance_to_earth_km"],
        ):
            best_by_month[month] = row

    return {
        "candidates_evaluated": len(rows),
        "valid_lunar_returns": len(valid),
        "valid_fair_returns": len(fair),
        "best_lunar_candidate": best,
        "per_month_valid_counts": dict(sorted(per_month_valid_counts.items())),
        "best_by_month": dict(sorted(best_by_month.items())),
    }
