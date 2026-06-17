"""
export_main_task_result.py
==========================
Assemble a single machine-readable main-task package for judge-side
verification without re-running heavy annual searches.

Outputs
-------
data/results/main_task_result.json
data/results/main_task_trajectory.csv
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
RESULTS = REPO / "data" / "results"
sys.path.insert(0, str(SRC))

from constants import AU_KM, GM_EARTH, GM_MOON, GM_SUN, R_EARTH
from budget_tools import (
    best_lunar_candidate,
    ensure_lunar_row_formal_fields,
    ensure_no_lunar_row_formal_fields,
    lunar_three_segment_budget,
    no_lunar_three_segment_budget,
    saving_ratio,
)
from mission_constraints import (
    MISSION_LAUNCH_END_DATE,
    MISSION_LAUNCH_START_DATE,
    is_launch_mjd_in_window,
    is_total_flight_time_valid,
    mjd_to_date_str,
)
from horizons import fetch_sem_vectors
from nbody import propagate_nbody
from trajectory import DesignParams, interpolate_state_at_mjd, solve_trajectory
from experiments.return_search_tools import search_best_return_event_detailed


def _load_json(name: str) -> dict[str, Any]:
    path = RESULTS / name
    if not path.exists():
        raise FileNotFoundError(f"required result file missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _best_from_rows(container: dict[str, Any], rows_key: str, summary_key: str) -> dict[str, Any] | None:
    rows = container.get(rows_key, [])
    best = best_lunar_candidate(rows, fair_only=True) if rows else None
    if best is not None:
        return best
    summary = container.get(summary_key)
    if isinstance(summary, dict):
        return ensure_lunar_row_formal_fields(summary)
    return None


def _best_t0_from_rows(container: dict[str, Any], rows_key: str, summary_key: str) -> float | None:
    best = _best_from_rows(container, rows_key, summary_key)
    if best is None:
        return None
    return float(best["t0_mjd"])


def _norm(vec: Any) -> float:
    return float(np.linalg.norm(np.asarray(vec, dtype=float)))


def _round(value: Any, ndigits: int = 6) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, str, bool)):
        return value
    return round(float(value), ndigits)


def _launch_direction(v_earth: np.ndarray, inward_transfer: bool = True) -> np.ndarray:
    earth_vel_dir = np.asarray(v_earth, dtype=float)
    earth_vel_dir = earth_vel_dir / (_norm(earth_vel_dir) + 1e-15)
    return -earth_vel_dir if inward_transfer else earth_vel_dir


def _build_sample_offsets(total_days: float, event_days: list[float]) -> list[float]:
    offsets: set[float] = set()
    max_day = max(total_days, 0.0)
    day = 0.0
    while day < max_day:
        offsets.add(round(day, 6))
        day += 1.0
    offsets.add(round(max_day, 6))
    for event_day in event_days:
        for extra in (-0.25, -1.0 / 24.0, 0.0, 1.0 / 24.0, 0.25):
            sample = event_day + extra
            if 0.0 <= sample <= max_day:
                offsets.add(round(sample, 6))
    return sorted(offsets)


def _event_flag(offset_days: float, launch_day: float, moon_day: float, peri_day: float, return_day: float) -> str:
    tags: list[str] = []
    for name, value in [
        ("launch", launch_day),
        ("moon_encounter", moon_day),
        ("perihelion", peri_day),
        ("earth_return", return_day),
    ]:
        if abs(offset_days - value) < 1e-7:
            tags.append(name)
    return ";".join(tags)


def _propagate_candidate_trajectory(
    *,
    candidate_label: str,
    t0_mjd: float,
    r_m_km: float,
    side: str,
    return_event_mjd: float,
    body_data: dict[str, Any],
    trajectory_dt_integrate_s: float = 900.0,
    nominal_window_half_width_days: float = 60.0,
    fallback_window_half_width_days: float = 180.0,
    coarse_step_days: float = 0.5,
    coarse_dt_internal_s: float = 3600.0,
    refine_step_s: float = 300.0,
    max_extra_days: float = 500.0,
) -> tuple[list[dict[str, Any]], dict[str, Any], Any]:
    params = DesignParams(
        t0_mjd=float(t0_mjd),
        r_m=float(r_m_km),
        side=str(side),
        r_p=0.3 * AU_KM,
    )
    traj = solve_trajectory(
        params,
        body_data=body_data,
        dt_integrate=trajectory_dt_integrate_s,
        verbose=False,
    )
    event_detail = search_best_return_event_detailed(
        traj=traj,
        body_data=body_data,
        launch_mjd=float(t0_mjd),
        nominal_return_mjd=float(return_event_mjd),
        threshold_km=1.5e6,
        nominal_window_half_width_days=nominal_window_half_width_days,
        fallback_window_half_width_days=fallback_window_half_width_days,
        coarse_step_days=coarse_step_days,
        coarse_dt_internal_s=coarse_dt_internal_s,
        refine_step_s=refine_step_s,
        max_extra_days=max_extra_days,
    )

    moon_day = float(traj.t_transfer_days)
    peri_day = float(traj.t_transfer_days + 0.5 * traj.t_coast_days)
    return_day = float(event_detail["return_event_mjd"] - t0_mjd)
    total_days = max(return_day, float(traj.t_total_days))
    sample_offsets = _build_sample_offsets(total_days, [moon_day, peri_day, return_day])

    gm = [GM_SUN, GM_EARTH, GM_MOON, 0.0]
    rows: list[dict[str, Any]] = []

    launch_dir = _launch_direction(traj.v_earth_t0, inward_transfer=(traj.elements.delta_v < 0.0))
    r_parking = R_EARTH * 1.1
    launch_sc = traj.r_earth_t0.copy() + r_parking * launch_dir
    launch_v = traj.v_earth_t0.copy() + traj.v_inf_earth * launch_dir

    def _make_row(
        offset_days: float,
        spacecraft_r: np.ndarray,
        spacecraft_v: np.ndarray,
        *,
        state_source: str,
    ) -> dict[str, Any]:
        mjd = float(t0_mjd + offset_days)
        r_sun_ref, v_sun_ref = interpolate_state_at_mjd(body_data, "Sun", mjd)
        r_earth_ref, v_earth_ref = interpolate_state_at_mjd(body_data, "Earth", mjd)
        r_moon_ref, v_moon_ref = interpolate_state_at_mjd(body_data, "Moon", mjd)
        return {
            "candidate_label": candidate_label,
            "mjd": _round(mjd, 6),
            "date": mjd_to_date_str(mjd),
            "time_since_launch_days": _round(offset_days, 6),
            "event_flags": _event_flag(offset_days, 0.0, moon_day, peri_day, return_day),
            "state_source": state_source,
            "spacecraft_x_km": _round(spacecraft_r[0], 3),
            "spacecraft_y_km": _round(spacecraft_r[1], 3),
            "spacecraft_vx_kms": _round(spacecraft_v[0], 6),
            "spacecraft_vy_kms": _round(spacecraft_v[1], 6),
            "earth_ref_x_km": _round(r_earth_ref[0], 3),
            "earth_ref_y_km": _round(r_earth_ref[1], 3),
            "earth_ref_vx_kms": _round(v_earth_ref[0], 6),
            "earth_ref_vy_kms": _round(v_earth_ref[1], 6),
            "moon_ref_x_km": _round(r_moon_ref[0], 3),
            "moon_ref_y_km": _round(r_moon_ref[1], 3),
            "moon_ref_vx_kms": _round(v_moon_ref[0], 6),
            "moon_ref_vy_kms": _round(v_moon_ref[1], 6),
            "sun_ref_x_km": _round(r_sun_ref[0], 3),
            "sun_ref_y_km": _round(r_sun_ref[1], 3),
            "distance_to_earth_ref_km": _round(_norm(spacecraft_r - r_earth_ref), 3),
            "distance_to_moon_ref_km": _round(_norm(spacecraft_r - r_moon_ref), 3),
            "distance_to_sun_ref_km": _round(_norm(spacecraft_r - r_sun_ref), 3),
        }

    rows.append(_make_row(0.0, launch_sc, launch_v, state_source="launch_proxy"))
    moon_row = _make_row(moon_day, traj.r_at_moon.copy(), traj.v_at_moon.copy(), state_source="solver_moon_encounter_pre_swingby")
    moon_row["distance_to_moon_ref_km"] = _round(_norm(traj.r_at_moon - traj.r_moon_at_encounter), 3)
    rows.append(moon_row)

    post_offsets = [value for value in sample_offsets if value > moon_day + 1e-9]
    moon_mjd = float(t0_mjd + moon_day)
    r_sun_moon, v_sun_moon = interpolate_state_at_mjd(body_data, "Sun", moon_mjd)
    r_earth_moon, v_earth_moon = interpolate_state_at_mjd(body_data, "Earth", moon_mjd)
    r_moon_moon, v_moon_moon = interpolate_state_at_mjd(body_data, "Moon", moon_mjd)
    r_state = [
        r_sun_moon.copy(),
        r_earth_moon.copy(),
        r_moon_moon.copy(),
        traj.r_at_moon.copy(),
    ]
    v_state = [
        v_sun_moon.copy(),
        v_earth_moon.copy(),
        v_moon_moon.copy(),
        traj.v_post_swingby.copy(),
    ]
    previous_offset = moon_day
    for offset_days in post_offsets:
        dt_sec = max(0.0, (offset_days - previous_offset) * 86400.0)
        if dt_sec > 0.0:
            r_state, v_state = propagate_nbody(
                r_state,
                v_state,
                dt_sec,
                gm,
                n_bodies=4,
                dt_internal=trajectory_dt_integrate_s,
            )
        previous_offset = offset_days
        rows.append(_make_row(offset_days, r_state[3].copy(), v_state[3].copy(), state_source="propagated_post_swingby"))

    min_moon_row = min(rows, key=lambda row: row["distance_to_moon_ref_km"])
    moon_and_after_rows = [row for row in rows if float(row["time_since_launch_days"]) >= moon_day - 1e-9]
    best_snapshot = event_detail["best_snapshot"]
    return_row = _make_row(
        return_day,
        np.asarray(best_snapshot["r_sc_km"], dtype=float),
        np.asarray(best_snapshot["v_sc_kms"], dtype=float),
        state_source="return_event_search_refined",
    )
    return_row["distance_to_earth_ref_km"] = _round(event_detail["event_distance_km"], 3)
    return_row["distance_to_moon_ref_km"] = _round(
        _norm(
            np.asarray(best_snapshot["r_sc_km"], dtype=float)
            - np.asarray(best_snapshot["r_moon_km"], dtype=float)
        ),
        3,
    )
    rows.append(return_row)
    rows = sorted(
        {(
            row["candidate_label"],
            row["mjd"],
            row["state_source"],
        ): row for row in rows}.values(),
        key=lambda row: (row["candidate_label"], float(row["time_since_launch_days"])),
    )
    min_earth_return_row = return_row
    peri_row = min(moon_and_after_rows or rows, key=lambda row: row["distance_to_sun_ref_km"])

    summary = {
        "sample_rows": len(rows),
        "moon_encounter_mjd": _round(t0_mjd + moon_day, 6),
        "perihelion_mjd_estimate": _round(t0_mjd + peri_day, 6),
        "return_event_mjd": _round(event_detail["return_event_mjd"], 6),
        "sampled_min_moon_distance_ref_km": _round(min_moon_row["distance_to_moon_ref_km"], 3) if min_moon_row else None,
        "sampled_min_moon_distance_mjd": min_moon_row["mjd"] if min_moon_row else None,
        "sampled_return_distance_ref_km": _round(min_earth_return_row["distance_to_earth_ref_km"], 3) if min_earth_return_row else None,
        "sampled_return_distance_mjd": min_earth_return_row["mjd"] if min_earth_return_row else None,
        "sampled_perihelion_distance_km": _round(peri_row["distance_to_sun_ref_km"], 3) if peri_row else None,
        "sampled_perihelion_AU": _round(peri_row["distance_to_sun_ref_km"] / AU_KM, 6) if peri_row else None,
        "sampled_perihelion_mjd": peri_row["mjd"] if peri_row else None,
        "return_event_detail": {
            "coarse_min_distance_km": _round(event_detail["coarse_min_distance_km"], 3),
            "refined_min_distance_km": _round(event_detail["refined_min_distance_km"], 3),
            "valid_return_event": bool(event_detail["valid_return_event"]),
            "return_vinf_kms": _round(event_detail["return_vinf_kms"], 4),
            "used_nominal_window": bool(event_detail["used_nominal_window"]),
            "fallback_full_window_used": bool(event_detail["fallback_full_window_used"]),
            "event_reason": event_detail["event_reason"],
        },
    }
    return rows, summary, traj


def _three_segment_budget_from_lunar_verify(verify: dict[str, Any]) -> dict[str, Any]:
    budget = verify["budget"]
    block = lunar_three_segment_budget(
        departure_vinf_kms=float(budget["departure_vinf_kms"]),
        lunar_residual_kms=float(budget["lunar_swingby_residual_kms"]),
        return_vinf_kms=float(budget["return_vinf_kms"]),
    )
    block["budget_definition"] = "three_segment_formal"
    block["note"] = "Matches the problem-statement three-term delta-v budget."
    return block


def _three_segment_budget_from_no_lunar(no_lunar_best: dict[str, Any]) -> dict[str, Any]:
    block = no_lunar_three_segment_budget(
        departure_vinf_kms=float(no_lunar_best["departure_vinf_kms"]),
        dsm_delta_v_kms=float(no_lunar_best["dsm_delta_v_kms"]),
        return_vinf_kms=float(no_lunar_best["return_vinf_kms"]),
    )
    block["dv_lunar_residual_kms"] = block.pop("dv_midcourse_kms")
    block["budget_definition"] = "three_segment_formal_no_lunar"
    block["note"] = "Here the middle term is DSM correction rather than lunar swingby residual."
    return block


def _canonical_three_segment_budget(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "budget_basis": block["budget_basis"],
        "dv_launch_kms": _round(block["dv_launch_kms"], 4),
        "dv_lunar_residual_kms": _round(block["dv_lunar_residual_kms"], 4),
        "dv_reentry_kms": _round(block["dv_reentry_kms"], 4),
        "dv_total_kms": _round(block["dv_total_kms"], 4),
        "budget_definition": block.get("budget_definition", "three_segment_formal"),
        "note": block.get("note"),
    }


def _canonical_compare_block(compare: dict[str, Any], no_lunar_best: dict[str, Any]) -> dict[str, Any]:
    compare = dict(compare)
    no_lunar_best = ensure_no_lunar_row_formal_fields(no_lunar_best)
    if compare.get("formal_ratio") is None:
        lunar_total = compare.get("lunar_total_dv_kms")
        no_lunar_total = compare.get("no_lunar_total_dv_kms")
        if lunar_total is not None and no_lunar_total is not None:
            compare["formal_ratio"] = round(saving_ratio(float(lunar_total), float(no_lunar_total)), 6)
    return {
        "same_t0_mjd": _round(compare["same_t0"], 6),
        "same_t0_date": compare["same_t0_date"],
        "same_budget_basis": bool(compare["same_budget_basis"]),
        "budget_basis": compare["budget_basis"],
        "formal_ratio": _round(compare["formal_ratio"], 6),
        "lunar_total_dv_kms": _round(compare["lunar_total_dv_kms"], 4),
        "no_lunar_total_dv_kms": _round(compare["no_lunar_total_dv_kms"], 4),
        "supplementary_vinf_basis_ratio": _round(compare.get("formal_ratio_vinf_basis"), 6),
        "no_lunar_best_valid": {
            "perihelion_AU": _round(no_lunar_best["perihelion_AU"], 6),
            "departure_vinf_kms": _round(no_lunar_best["departure_vinf_kms"], 4),
            "dsm_delta_v_kms": _round(no_lunar_best["dsm_delta_v_kms"], 4),
            "return_vinf_kms": _round(no_lunar_best["return_vinf_kms"], 4),
            "total_vinf_basis_kms": _round(no_lunar_best.get("total_dv_proxy_kms"), 4),
            "three_segment_budget": _canonical_three_segment_budget(
                _three_segment_budget_from_no_lunar(no_lunar_best)
            ),
            "three_segment_budget_proxy": _canonical_three_segment_budget(
                _three_segment_budget_from_no_lunar(no_lunar_best)
            ),
        },
    }


def _fixed_date_formal_block(
    verify: dict[str, Any],
    compare: dict[str, Any],
    no_lunar: dict[str, Any],
    body_data: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidate = verify["candidate"]
    event_check = verify["event_check"]
    state = verify["state_at_return"]
    budget = verify["budget"]
    rows, traj_summary, traj = _propagate_candidate_trajectory(
        candidate_label="fixed_date_formal_anchor",
        t0_mjd=float(candidate["t0_mjd"]),
        r_m_km=float(candidate["r_m_km"]),
        side=str(candidate["side"]),
        return_event_mjd=float(event_check["return_epoch_mjd"]),
        body_data=body_data,
    )

    block = {
        "candidate_label": "fixed_date_formal_anchor",
        "classification": verify.get("classification"),
        "formal_result_eligible": bool(verify.get("formal_result_eligible")),
        "launch_window_valid": bool(candidate.get("launch_window_valid")),
        "launch_window": [MISSION_LAUNCH_START_DATE, MISSION_LAUNCH_END_DATE],
        "t0_mjd": _round(candidate["t0_mjd"], 6),
        "t0_date": candidate["t0_date"],
        "side": candidate["side"],
        "r_m_design_km": _round(candidate["r_m_km"], 1),
        "mission_duration_days_to_return": _round(float(event_check["return_epoch_mjd"]) - float(candidate["t0_mjd"]), 6),
        "duration_constraint_valid": is_total_flight_time_valid(float(event_check["return_epoch_mjd"]) - float(candidate["t0_mjd"])),
        "moon_encounter_mjd": traj_summary["moon_encounter_mjd"],
        "moon_encounter_details": {
            "spacecraft_to_moon_distance_km": _round(traj.dist_moon_min, 3),
            "spacecraft_x_km": _round(traj.r_at_moon[0], 3),
            "spacecraft_y_km": _round(traj.r_at_moon[1], 3),
            "moon_x_km": _round(traj.r_moon_at_encounter[0], 3),
            "moon_y_km": _round(traj.r_moon_at_encounter[1], 3),
            "spacecraft_rel_moon_speed_kms_pre_swingby": _round(_norm(traj.v_at_moon - traj.v_moon_at_encounter), 6),
            "spacecraft_rel_moon_speed_kms_post_swingby": _round(_norm(traj.v_post_swingby - traj.v_moon_at_encounter), 6),
        },
        "perihelion_mjd_estimate": traj_summary["sampled_perihelion_mjd"],
        "return_event_mjd": _round(event_check["return_epoch_mjd"], 6),
        "nearest_moon_distance_model_km": _round(traj.dist_moon_min, 3),
        "nearest_moon_distance_ref_sampled_km": traj_summary["sampled_min_moon_distance_ref_km"],
        "perihelion_achieved_AU": _round(verify["trajectory_summary"]["r_p_achieved_AU"], 6),
        "perihelion_sampled_AU": traj_summary["sampled_perihelion_AU"],
        "distance_to_earth_km": _round(event_check["distance_to_earth_km"], 3),
        "return_distance_ref_sampled_km": traj_summary["sampled_return_distance_ref_km"],
        "return_vinf_kms": _round(state["return_vinf_kms"], 4),
        "valid_return_event": bool(event_check["valid_return_event"]),
        "event_type": event_check["event_type"],
        "three_segment_budget": _canonical_three_segment_budget(_three_segment_budget_from_lunar_verify(verify)),
        "three_segment_budget_proxy": _canonical_three_segment_budget(_three_segment_budget_from_lunar_verify(verify)),
        "vinf_basis_budget": {
            "departure_vinf_kms": _round(budget["departure_vinf_kms"], 4),
            "return_vinf_kms": _round(budget["return_vinf_kms"], 4),
            "total_vinf_basis_kms": _round(budget["total_dv_proxy_vinf_basis"], 4),
            "note": budget["note"],
        },
        "same_date_no_lunar_compare": _canonical_compare_block(compare, no_lunar["best_valid"]),
        "source_files": [
            "data/results/m5_best_lunar_candidate_verify.json",
            "data/results/m5_fixed_date_current_compare.json",
            "data/results/m5_no_lunar_fixed_date_deep_search.json",
        ],
        "trajectory_rows_file": "data/results/main_task_trajectory.csv",
    }
    return block, rows


def _best_legal_window_block(
    legal_m5: dict[str, Any],
    legal_m6: dict[str, Any],
    body_data: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidate = _best_from_rows(legal_m6, "candidates", "best_valid_candidate")
    if candidate is None:
        raise ValueError("m6_independent_window_search.json does not contain a valid fair candidate")
    m5_best = _best_from_rows(legal_m5, "search_rows", "best_lunar_candidate")
    if m5_best is None:
        raise ValueError("m5_legal_window_search.json does not contain a valid fair candidate")
    search_space = legal_m6.get("search_space", {})
    rows, traj_summary, traj = _propagate_candidate_trajectory(
        candidate_label="best_legal_window_candidate",
        t0_mjd=float(candidate["t0_mjd"]),
        r_m_km=float(candidate["r_m_km"]),
        side=str(candidate["side"]),
        return_event_mjd=float(candidate["return_event_mjd"]),
        body_data=body_data,
        trajectory_dt_integrate_s=float(search_space.get("refine_trajectory_dt_integrate_s", 900.0)),
        nominal_window_half_width_days=float(search_space.get("refine_nominal_window_half_width_days", 180.0)),
        fallback_window_half_width_days=float(search_space.get("refine_fallback_window_half_width_days", 360.0)),
        coarse_step_days=float(search_space.get("refine_event_coarse_step_days", 0.25)),
        coarse_dt_internal_s=float(search_space.get("refine_coarse_dt_internal_s", 1800.0)),
        refine_step_s=float(search_space.get("refine_event_refine_step_s", 300.0)),
        max_extra_days=float(search_space.get("max_extra_days", 500.0)),
    )
    three_segment = _canonical_three_segment_budget({
        **lunar_three_segment_budget(
            departure_vinf_kms=float(candidate["departure_vinf_kms"]),
            lunar_residual_kms=float(candidate["swingby_dv_kms"]),
            return_vinf_kms=float(candidate["return_vinf_kms"]),
        ),
        "budget_definition": "three_segment_formal",
        "note": "Reconstructed from candidate fields with the formal three-segment budget.",
    })
    block = {
        "candidate_label": "best_legal_window_candidate",
        "classification": legal_m6.get("classification"),
        "launch_window_valid": is_launch_mjd_in_window(float(candidate["t0_mjd"])),
        "launch_window": legal_m6.get("launch_window", [MISSION_LAUNCH_START_DATE, MISSION_LAUNCH_END_DATE]),
        "t0_mjd": _round(candidate["t0_mjd"], 6),
        "t0_date": candidate["t0_date"],
        "side": candidate["side"],
        "r_m_design_km": _round(candidate["r_m_km"], 1),
        "mission_duration_days_to_return": _round(float(candidate["return_event_mjd"]) - float(candidate["t0_mjd"]), 6),
        "duration_constraint_valid": is_total_flight_time_valid(float(candidate["return_event_mjd"]) - float(candidate["t0_mjd"])),
        "moon_encounter_mjd": traj_summary["moon_encounter_mjd"],
        "moon_encounter_details": {
            "spacecraft_to_moon_distance_km": _round(traj.dist_moon_min, 3),
            "spacecraft_x_km": _round(traj.r_at_moon[0], 3),
            "spacecraft_y_km": _round(traj.r_at_moon[1], 3),
            "moon_x_km": _round(traj.r_moon_at_encounter[0], 3),
            "moon_y_km": _round(traj.r_moon_at_encounter[1], 3),
            "spacecraft_rel_moon_speed_kms_pre_swingby": _round(_norm(traj.v_at_moon - traj.v_moon_at_encounter), 6),
            "spacecraft_rel_moon_speed_kms_post_swingby": _round(_norm(traj.v_post_swingby - traj.v_moon_at_encounter), 6),
        },
        "perihelion_mjd_estimate": traj_summary["sampled_perihelion_mjd"],
        "return_event_mjd": _round(candidate["return_event_mjd"], 6),
        "nearest_moon_distance_model_km": _round(traj.dist_moon_min, 3),
        "nearest_moon_distance_ref_sampled_km": traj_summary["sampled_min_moon_distance_ref_km"],
        "perihelion_achieved_AU": _round(candidate["perihelion_AU"], 6),
        "perihelion_sampled_AU": traj_summary["sampled_perihelion_AU"],
        "distance_to_earth_km": _round(candidate["distance_to_earth_km"], 3),
        "return_distance_ref_sampled_km": traj_summary["sampled_return_distance_ref_km"],
        "return_vinf_kms": _round(candidate["return_vinf_kms"], 4),
        "valid_return_event": bool(candidate["valid_return_event"]),
        "fair": bool(candidate["fair"]),
        "vinf_basis_budget": {
            "departure_vinf_kms": _round(candidate["departure_vinf_kms"], 4),
            "return_vinf_kms": _round(candidate["return_vinf_kms"], 4),
            "return_braking_proxy_kms": _round(max(0.0, float(candidate["return_vinf_kms"]) - 15.0), 4),
            "total_vinf_basis_kms": _round(candidate["total_vinf_basis_kms"], 4),
        },
        "three_segment_budget": three_segment,
        "three_segment_budget_proxy": three_segment,
        "provenance": {
            "candidate_source": legal_m6.get("candidate_source"),
            "independent_m6_search": bool(legal_m6.get("independent_m6_search")),
            "source_grid_reused": bool(legal_m6.get("source_grid_reused")),
            "m6_interpretation": legal_m6.get("m6_interpretation"),
            "m5_legal_window_best_crosscheck": {
                "t0_mjd": _round(m5_best["t0_mjd"], 6),
                "r_m_km": _round(m5_best["r_m_km"], 1),
                "distance_to_earth_km": _round(m5_best["distance_to_earth_km"], 3),
                "return_vinf_kms": _round(m5_best["return_vinf_kms"], 4),
            },
            "single_candidate_replay_crosscheck": {
                "trajectory_dt_integrate_s": float(search_space.get("refine_trajectory_dt_integrate_s", 900.0)),
                "event_coarse_step_days": float(search_space.get("refine_event_coarse_step_days", 0.25)),
                "event_refine_step_s": float(search_space.get("refine_event_refine_step_s", 300.0)),
                "search_summary_distance_to_earth_km": _round(candidate["distance_to_earth_km"], 3),
                "replayed_distance_to_earth_km": traj_summary["sampled_return_distance_ref_km"],
                "search_summary_return_vinf_kms": _round(candidate["return_vinf_kms"], 4),
                "replayed_return_vinf_kms": traj_summary["return_event_detail"]["return_vinf_kms"],
                "status": (
                    "MATCH"
                    if traj_summary["sampled_return_distance_ref_km"] is not None
                    and abs(float(traj_summary["sampled_return_distance_ref_km"]) - float(candidate["distance_to_earth_km"])) <= 2.0e4
                    else "SENSITIVE_REPLAY_MISMATCH"
                ),
                "note": (
                    "The legal-window best candidate is preserved as a search-summary result. "
                    "Single-candidate replay is exported separately because this narrow window is step-size/event-search sensitive."
                ),
            },
        },
        "source_files": [
            "data/results/m5_legal_window_search.json",
            "data/results/m6_independent_window_search.json",
        ],
        "trajectory_rows_file": "data/results/main_task_trajectory.csv",
    }
    return block, rows


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("no trajectory rows to write")
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    body_data = fetch_sem_vectors(use_cache=True)

    verify = _load_json("m5_best_lunar_candidate_verify.json")
    compare = _load_json("m5_fixed_date_current_compare.json")
    no_lunar = _load_json("m5_no_lunar_fixed_date_deep_search.json")
    legal_m5 = _load_json("m5_legal_window_search.json")
    legal_m6 = _load_json("m6_independent_window_search.json")
    invalidated = _load_json("m5_saving_ratio_resolved.json")

    fixed_block, fixed_rows = _fixed_date_formal_block(verify, compare, no_lunar, body_data)
    legal_block, legal_rows = _best_legal_window_block(legal_m5, legal_m6, body_data)
    m7 = _load_json("m7_extended_monte_carlo.json")

    payload = {
        "task": "Unified machine-readable main-task export",
        "classification": "MAIN_TASK_FORMAL_EXPORT",
        "launch_window": [MISSION_LAUNCH_START_DATE, MISSION_LAUNCH_END_DATE],
        "historical_invalidated_anchor": {
            "t0_mjd": 61037.0,
            "t0_date": mjd_to_date_str(61037.0),
            "status": "invalidated_outside_2026_launch_window",
            "invalidated_formal_ratio": 0.557881,
            "source_file": "data/results/m5_saving_ratio_resolved.json",
        },
        "fixed_date_formal_anchor": fixed_block,
        "best_legal_window_candidate": legal_block,
        "annual_scan_summary": {
            "m5_legal_window_search": {
                "classification": legal_m5.get("classification"),
                "candidates_evaluated": legal_m5.get("candidates_evaluated"),
                "valid_lunar_returns": legal_m5.get("valid_lunar_returns"),
                "valid_fair_returns": legal_m5.get("valid_fair_returns"),
                "best_lunar_candidate_t0_mjd": _best_t0_from_rows(legal_m5, "search_rows", "best_lunar_candidate"),
                "full_year_fine_search_pending": legal_m5.get("full_year_fine_search_pending"),
            },
            "m6_independent_window_search": {
                "classification": legal_m6.get("classification"),
                "total_candidates_evaluated": legal_m6.get("total_candidates_evaluated"),
                "valid_complete_return_count": legal_m6.get("valid_complete_return_count"),
                "valid_fair_return_count": legal_m6.get("valid_fair_return_count"),
                "best_valid_candidate_t0_mjd": _best_t0_from_rows(legal_m6, "candidates", "best_valid_candidate"),
            },
        },
        "m7_context": {
            "classification": m7.get("classification"),
            "reference_candidate_t0_mjd": m7.get("reference_candidate", {}).get("t0_mjd"),
            "valid_return_count": m7.get("valid_return_count"),
            "valid_return_rate": m7.get("valid_return_rate"),
        },
        "invalidated_formal_results_guard": {
            "resolver_status": invalidated.get("status"),
            "current_formal_fixed_date_ratio": invalidated.get("formal_fixed_date_ratio"),
        },
        "machine_readable_outputs": {
            "summary_json": "data/results/main_task_result.json",
            "trajectory_csv": "data/results/main_task_trajectory.csv",
            "trajectory_candidates": [
                "fixed_date_formal_anchor",
                "best_legal_window_candidate",
            ],
        },
        "notes": [
            "This export does not rerun heavy annual searches; it assembles already validated legal/formal outputs and regenerates only two single-candidate trajectory sequences.",
            "The formal budget in this export is the problem-statement three-segment delta-v definition; vinf_basis is retained only as a supplementary diagnostic.",
            "Earth-return validity uses explicit event semantics: return_vinf is only defined at a real Earth-return event.",
            "The fixed-date formal anchor (61065.0) is the strongest fully reconstructed formal result in this export.",
            "The best legal-window candidate is recomputed from the stored candidate pool under the formal three-segment budget, rather than trusting stale summary fields from earlier vinf-basis ranking passes.",
            "The current best legal-window candidate remains a search-summary result with explicit replay crosscheck metadata; it is not overstated as a stronger fully reconstructed formal result than the fixed-date anchor.",
        ],
    }

    json_path = RESULTS / "main_task_result.json"
    csv_path = RESULTS / "main_task_trajectory.csv"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(fixed_rows + legal_rows, csv_path)

    print(f"[OK] wrote {json_path}")
    print(f"[OK] wrote {csv_path}")
    print(f"  fixed_date_formal_anchor t0 = {fixed_block['t0_date']} ({fixed_block['t0_mjd']})")
    print(f"  best_legal_window_candidate t0 = {legal_block['t0_date']} ({legal_block['t0_mjd']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
