"""
return_search_tools.py
======================
Shared return-event search helpers for numerical result checks.

These helpers:
  - propagate from post-perihelion states,
  - search around a nominal Earth-return window first,
  - fall back to a wider search if needed,
  - define return_vinf only through event semantics.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from constants import GM_EARTH, GM_MOON, GM_SUN
from event_semantics import compute_earth_return_vinf
from nbody import propagate_nbody
from trajectory import interpolate_state_at_mjd


def _clone_state(r_state, v_state):
    return [r.copy() for r in r_state], [v.copy() for v in v_state]


def _norm(vec: np.ndarray) -> float:
    return float(np.linalg.norm(vec))


def _sync_earth_moon(body_data: dict, mjd: float, r_state, v_state) -> None:
    r_earth, v_earth = interpolate_state_at_mjd(body_data, "Earth", mjd)
    r_state[1] = r_earth.copy()
    v_state[1] = v_earth.copy()
    r_moon, v_moon = interpolate_state_at_mjd(body_data, "Moon", mjd)
    r_state[2] = r_moon.copy()
    v_state[2] = v_moon.copy()


def _snapshot(mjd: float, r_state, v_state) -> dict[str, Any]:
    return {
        "mjd": float(mjd),
        "r_sc": r_state[3].copy(),
        "v_sc": v_state[3].copy(),
        "r_earth": r_state[1].copy(),
        "v_earth": v_state[1].copy(),
        "r_moon": r_state[2].copy(),
        "dist_km": _norm(r_state[3] - r_state[1]),
    }


def _refine_window(
    body_data: dict,
    gm: list[float],
    anchor_mjd: float,
    anchor_r,
    anchor_v,
    window_center_mjd: float,
    window_half_width_days: float,
    max_extra_days: float,
    coarse_dt_internal_s: float,
    refine_step_s: float,
) -> dict[str, Any]:
    start_mjd = max(anchor_mjd, window_center_mjd - window_half_width_days)
    end_mjd = min(anchor_mjd + max_extra_days, window_center_mjd + window_half_width_days)

    r_state, v_state = _clone_state(anchor_r, anchor_v)
    if start_mjd > anchor_mjd:
        r_state, v_state = propagate_nbody(
            r_state,
            v_state,
            (start_mjd - anchor_mjd) * 86400.0,
            gm,
            n_bodies=4,
            dt_internal=coarse_dt_internal_s,
        )
    _sync_earth_moon(body_data, start_mjd, r_state, v_state)
    best = _snapshot(start_mjd, r_state, v_state)

    n_steps = int(math.ceil((end_mjd - start_mjd) * 86400.0 / refine_step_s))
    cur_mjd = start_mjd
    for _ in range(max(n_steps, 1)):
        r_state, v_state = propagate_nbody(
            r_state,
            v_state,
            refine_step_s,
            gm,
            n_bodies=4,
            dt_internal=refine_step_s,
        )
        cur_mjd += refine_step_s / 86400.0
        _sync_earth_moon(body_data, cur_mjd, r_state, v_state)
        cur = _snapshot(cur_mjd, r_state, v_state)
        if cur["dist_km"] < best["dist_km"]:
            best = cur
    return best


def search_best_return_event(
    traj,
    body_data: dict,
    launch_mjd: float,
    nominal_return_mjd: float,
    threshold_km: float,
    nominal_window_half_width_days: float = 60.0,
    fallback_window_half_width_days: float = 180.0,
    coarse_step_days: float = 2.0,
    coarse_dt_internal_s: float = 10800.0,
    refine_step_s: float = 3600.0,
    max_extra_days: float = 500.0,
) -> dict[str, Any]:
    result = search_best_return_event_detailed(
        traj=traj,
        body_data=body_data,
        launch_mjd=launch_mjd,
        nominal_return_mjd=nominal_return_mjd,
        threshold_km=threshold_km,
        nominal_window_half_width_days=nominal_window_half_width_days,
        fallback_window_half_width_days=fallback_window_half_width_days,
        coarse_step_days=coarse_step_days,
        coarse_dt_internal_s=coarse_dt_internal_s,
        refine_step_s=refine_step_s,
        max_extra_days=max_extra_days,
    )
    result.pop("best_snapshot", None)
    result.pop("coarse_best_snapshot", None)
    return result


def search_best_return_event_detailed(
    traj,
    body_data: dict,
    launch_mjd: float,
    nominal_return_mjd: float,
    threshold_km: float,
    nominal_window_half_width_days: float = 60.0,
    fallback_window_half_width_days: float = 180.0,
    coarse_step_days: float = 2.0,
    coarse_dt_internal_s: float = 10800.0,
    refine_step_s: float = 3600.0,
    max_extra_days: float = 500.0,
) -> dict[str, Any]:
    t_end = float(launch_mjd) + float(traj.t_total_days)
    r_sun_end, v_sun_end = interpolate_state_at_mjd(body_data, "Sun", t_end)
    r_moon_end, v_moon_end = interpolate_state_at_mjd(body_data, "Moon", t_end)
    gm = [GM_SUN, GM_EARTH, GM_MOON, 0.0]

    r_state = [
        r_sun_end.copy(),
        traj.r_earth_final.copy(),
        r_moon_end.copy(),
        traj.r_final.copy(),
    ]
    v_state = [
        v_sun_end.copy(),
        traj.v_earth_final.copy(),
        v_moon_end.copy(),
        traj.v_final.copy(),
    ]
    _sync_earth_moon(body_data, t_end, r_state, v_state)

    coarse_step_sec = coarse_step_days * 86400.0
    coarse_steps = int(math.ceil(max_extra_days / coarse_step_days))
    coarse_best = _snapshot(t_end, r_state, v_state)
    coarse_states: list[tuple[float, list[np.ndarray], list[np.ndarray]]] = [
        (t_end, *_clone_state(r_state, v_state))
    ]

    for step_idx in range(1, coarse_steps + 1):
        r_state, v_state = propagate_nbody(
            r_state,
            v_state,
            coarse_step_sec,
            gm,
            n_bodies=4,
            dt_internal=coarse_dt_internal_s,
        )
        cur_mjd = t_end + step_idx * coarse_step_days
        _sync_earth_moon(body_data, cur_mjd, r_state, v_state)
        cur = _snapshot(cur_mjd, r_state, v_state)
        coarse_states.append((cur_mjd, *_clone_state(r_state, v_state)))
        if cur["dist_km"] < coarse_best["dist_km"]:
            coarse_best = cur

    anchor_mjd = coarse_states[0][0]
    anchor_r = coarse_states[0][1]
    anchor_v = coarse_states[0][2]
    nominal_start = max(t_end, nominal_return_mjd - nominal_window_half_width_days)
    for mjd, r_snap, v_snap in coarse_states:
        if mjd <= nominal_start:
            anchor_mjd, anchor_r, anchor_v = mjd, r_snap, v_snap
        else:
            break

    nominal_best = _refine_window(
        body_data=body_data,
        gm=gm,
        anchor_mjd=anchor_mjd,
        anchor_r=anchor_r,
        anchor_v=anchor_v,
        window_center_mjd=nominal_return_mjd,
        window_half_width_days=nominal_window_half_width_days,
        max_extra_days=max_extra_days,
        coarse_dt_internal_s=coarse_dt_internal_s,
        refine_step_s=refine_step_s,
    )

    used_nominal_window = True
    fallback_full_window_used = False
    best = nominal_best if nominal_best["dist_km"] <= coarse_best["dist_km"] else coarse_best

    if best["dist_km"] > threshold_km:
        fallback_full_window_used = True
        fallback_best = _refine_window(
            body_data=body_data,
            gm=gm,
            anchor_mjd=coarse_states[0][0],
            anchor_r=coarse_states[0][1],
            anchor_v=coarse_states[0][2],
            window_center_mjd=coarse_best["mjd"],
            window_half_width_days=fallback_window_half_width_days,
            max_extra_days=max_extra_days,
            coarse_dt_internal_s=coarse_dt_internal_s,
            refine_step_s=refine_step_s,
        )
        if fallback_best["dist_km"] < best["dist_km"]:
            best = fallback_best

    event = compute_earth_return_vinf(
        best["r_sc"],
        best["v_sc"],
        best["r_earth"],
        best["v_earth"],
        threshold_km=threshold_km,
    )
    dist_moon = _norm(best["r_sc"] - best["r_moon"])
    return {
        "coarse_min_distance_km": round(coarse_best["dist_km"], 1),
        "refined_min_distance_km": round(best["dist_km"], 1),
        "return_event_mjd": round(best["mjd"], 2),
        "valid_return_event": bool(event["valid_return_event"]),
        "return_vinf_kms": event["return_vinf_kms"],
        "event_distance_km": round(best["dist_km"], 1),
        "distance_to_moon_km": round(dist_moon, 1),
        "used_nominal_window": used_nominal_window,
        "fallback_full_window_used": fallback_full_window_used,
        "event_reason": event["reason"],
        "best_snapshot": {
            "mjd": float(best["mjd"]),
            "r_sc_km": [float(x) for x in best["r_sc"]],
            "v_sc_kms": [float(x) for x in best["v_sc"]],
            "r_earth_km": [float(x) for x in best["r_earth"]],
            "v_earth_kms": [float(x) for x in best["v_earth"]],
            "r_moon_km": [float(x) for x in best["r_moon"]],
        },
        "coarse_best_snapshot": {
            "mjd": float(coarse_best["mjd"]),
            "r_sc_km": [float(x) for x in coarse_best["r_sc"]],
            "v_sc_kms": [float(x) for x in coarse_best["v_sc"]],
            "r_earth_km": [float(x) for x in coarse_best["r_earth"]],
            "v_earth_kms": [float(x) for x in coarse_best["v_earth"]],
            "r_moon_km": [float(x) for x in coarse_best["r_moon"]],
        },
    }
