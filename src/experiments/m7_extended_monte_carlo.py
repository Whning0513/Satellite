"""
m7_extended_monte_carlo.py
==========================
Formal M7 Monte Carlo with explicit smoke/full identities,
Earth-return event semantics, and optional replayable sample outputs.

This file is now structured so a future heavy run can directly emit:
  - summary JSON
  - per-sample JSON / CSV
  - timeout replay manifest

without needing further code changes.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import AU_KM, GM_EARTH, GM_MOON, GM_SUN
from event_semantics import compute_earth_return_vinf
from horizons import fetch_sem_vectors
from mission_constraints import is_launch_mjd_in_window
from nbody import propagate_nbody
from trajectory import DesignParams, interpolate_state_at_mjd, solve_trajectory


RESULTS = _REPO / "data" / "results"
M5_VERIFY = RESULTS / "m5_best_lunar_candidate_verify.json"

M5_VALID_T0 = 61065.0
M5_VALID_RM_KM = 1837.4
M5_VALID_SIDE = "trailing"
M5_VALID_RP_AU = 0.3
M5_VALID_RETURN_MJD = 61431.12

EARTH_RETURN_THRESHOLD_KM = 1.5e6
DEFAULT_N_FULL = 200
DEFAULT_N_SMOKE = 20
DEFAULT_SEED = 202606
DEFAULT_MAX_WORKERS = 1
DEFAULT_MAX_RUNTIME_SEC = 1800.0
DEFAULT_MAX_RUNTIME_PER_SAMPLE_SEC = 120.0

COARSE_STEP_DAYS = 2.0
COARSE_DT_INTERNAL_S = 10800.0
REFINE_STEP_S = 3600.0
NOMINAL_WINDOW_HALF_WIDTH_DAYS = 30.0
FALLBACK_WINDOW_HALF_WIDTH_DAYS = 60.0
MAX_EXTRA_DAYS = 360.0

_BODY_DATA_CACHE: dict[str, Any] | None = None


def _quantiles(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    arr = np.asarray(values, dtype=float)
    return {
        "mean": round(float(arr.mean()), 6),
        "std": round(float(arr.std()), 6),
        "p5": round(float(np.percentile(arr, 5)), 6),
        "p50": round(float(np.percentile(arr, 50)), 6),
        "p95": round(float(np.percentile(arr, 95)), 6),
    }


def _load_nominal_return_mjd() -> float:
    if not M5_VERIFY.exists():
        return M5_VALID_RETURN_MJD
    data = json.loads(M5_VERIFY.read_text(encoding="utf-8"))
    return float(data["event_check"]["return_epoch_mjd"])


def _load_reference_candidate() -> dict[str, Any]:
    if not M5_VERIFY.exists():
        return {
            "source": "built_in_fallback",
            "t0_mjd": M5_VALID_T0,
            "r_m_km": M5_VALID_RM_KM,
            "side": M5_VALID_SIDE,
            "target_rp_AU": M5_VALID_RP_AU,
            "nominal_return_mjd": M5_VALID_RETURN_MJD,
        }
    data = json.loads(M5_VERIFY.read_text(encoding="utf-8"))
    candidate = data.get("candidate", {})
    event = data.get("event_check", {})
    traj = data.get("trajectory_summary", {})
    ref = {
        "source": "m5_best_lunar_candidate_verify.json",
        "t0_mjd": float(candidate.get("t0_mjd", M5_VALID_T0)),
        "r_m_km": float(candidate.get("r_m_km", M5_VALID_RM_KM)),
        "side": candidate.get("side", M5_VALID_SIDE),
        "target_rp_AU": float(traj.get("r_p_achieved_AU", M5_VALID_RP_AU)),
        "nominal_return_mjd": float(event.get("return_epoch_mjd", M5_VALID_RETURN_MJD)),
    }
    if not is_launch_mjd_in_window(ref["t0_mjd"]):
        raise ValueError(
            f"M7 reference candidate t0={ref['t0_mjd']} is outside the formal 2026 launch window"
        )
    return ref


def _clone_state(r_state, v_state):
    return [r.copy() for r in r_state], [v.copy() for v in v_state]


def _sync_earth_moon(body_data: dict, mjd: float, r_state, v_state) -> None:
    r_earth, v_earth = interpolate_state_at_mjd(body_data, "Earth", mjd)
    r_state[1] = r_earth.copy()
    v_state[1] = v_earth.copy()
    r_moon, v_moon = interpolate_state_at_mjd(body_data, "Moon", mjd)
    r_state[2] = r_moon.copy()
    v_state[2] = v_moon.copy()


def _candidate_event_summary(mjd: float, r_state, v_state) -> dict[str, Any]:
    return {
        "mjd": mjd,
        "r_sc": r_state[3].copy(),
        "v_sc": v_state[3].copy(),
        "r_earth": r_state[1].copy(),
        "v_earth": v_state[1].copy(),
        "dist_km": float(np.linalg.norm(r_state[3] - r_state[1])),
    }


def _refine_window(
    body_data: dict,
    gm: list[float],
    anchor_mjd: float,
    anchor_r,
    anchor_v,
    window_center_mjd: float,
    window_half_width_days: float,
) -> dict[str, Any]:
    start_mjd = max(anchor_mjd, window_center_mjd - window_half_width_days)
    end_mjd = min(anchor_mjd + MAX_EXTRA_DAYS, window_center_mjd + window_half_width_days)

    r_state, v_state = _clone_state(anchor_r, anchor_v)
    if start_mjd > anchor_mjd:
        r_state, v_state = propagate_nbody(
            r_state,
            v_state,
            (start_mjd - anchor_mjd) * 86400.0,
            gm,
            n_bodies=4,
            dt_internal=COARSE_DT_INTERNAL_S,
        )
    _sync_earth_moon(body_data, start_mjd, r_state, v_state)
    best = _candidate_event_summary(start_mjd, r_state, v_state)

    n_steps = int(math.ceil((end_mjd - start_mjd) * 86400.0 / REFINE_STEP_S))
    cur_mjd = start_mjd
    for _ in range(max(n_steps, 1)):
        r_state, v_state = propagate_nbody(
            r_state, v_state, REFINE_STEP_S, gm, n_bodies=4, dt_internal=REFINE_STEP_S
        )
        cur_mjd += REFINE_STEP_S / 86400.0
        _sync_earth_moon(body_data, cur_mjd, r_state, v_state)
        cur = _candidate_event_summary(cur_mjd, r_state, v_state)
        if cur["dist_km"] < best["dist_km"]:
            best = cur
        if best["dist_km"] < EARTH_RETURN_THRESHOLD_KM and cur["dist_km"] > best["dist_km"] * 2.0:
            break
    return best


def _search_return_event(
    traj,
    body_data: dict,
    launch_mjd: float,
    nominal_return_mjd: float,
) -> dict[str, Any]:
    t_end = launch_mjd + traj.t_total_days
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

    coarse_start = time.perf_counter()
    coarse_step_sec = COARSE_STEP_DAYS * 86400.0
    coarse_steps = int(math.ceil(MAX_EXTRA_DAYS / COARSE_STEP_DAYS))
    coarse_best = _candidate_event_summary(t_end, r_state, v_state)
    coarse_states: list[tuple[float, list[np.ndarray], list[np.ndarray]]] = [(t_end, *_clone_state(r_state, v_state))]
    for step_idx in range(1, coarse_steps + 1):
        r_state, v_state = propagate_nbody(
            r_state, v_state, coarse_step_sec, gm, n_bodies=4, dt_internal=COARSE_DT_INTERNAL_S
        )
        cur_mjd = t_end + step_idx * COARSE_STEP_DAYS
        _sync_earth_moon(body_data, cur_mjd, r_state, v_state)
        cur = _candidate_event_summary(cur_mjd, r_state, v_state)
        coarse_states.append((cur_mjd, *_clone_state(r_state, v_state)))
        if cur["dist_km"] < coarse_best["dist_km"]:
            coarse_best = cur
        if coarse_best["dist_km"] < EARTH_RETURN_THRESHOLD_KM and cur["dist_km"] > coarse_best["dist_km"] * 2.0:
            break
    coarse_time = time.perf_counter() - coarse_start

    anchor_mjd = t_end
    anchor_r, anchor_v = coarse_states[0][1], coarse_states[0][2]
    nominal_start = max(t_end, nominal_return_mjd - NOMINAL_WINDOW_HALF_WIDTH_DAYS)
    for mjd, r_snap, v_snap in coarse_states:
        if mjd <= nominal_start:
            anchor_mjd = mjd
            anchor_r, anchor_v = r_snap, v_snap
        else:
            break

    refine_start = time.perf_counter()
    nominal_best = _refine_window(
        body_data,
        gm,
        anchor_mjd,
        anchor_r,
        anchor_v,
        nominal_return_mjd,
        NOMINAL_WINDOW_HALF_WIDTH_DAYS,
    )
    refine_time = time.perf_counter() - refine_start

    used_nominal_window = True
    fallback_full_window_used = False
    best = nominal_best if nominal_best["dist_km"] <= coarse_best["dist_km"] else coarse_best

    if best["dist_km"] > EARTH_RETURN_THRESHOLD_KM:
        fallback_full_window_used = True
        fallback_start = time.perf_counter()
        fallback_best = _refine_window(
            body_data,
            gm,
            coarse_states[0][0],
            coarse_states[0][1],
            coarse_states[0][2],
            nominal_return_mjd,
            FALLBACK_WINDOW_HALF_WIDTH_DAYS,
        )
        refine_time += time.perf_counter() - fallback_start
        if fallback_best["dist_km"] < best["dist_km"]:
            best = fallback_best

    check = compute_earth_return_vinf(best["r_sc"], best["v_sc"], best["r_earth"], best["v_earth"])
    return {
        "coarse_min_distance_km": round(coarse_best["dist_km"], 1),
        "refined_min_distance_km": round(best["dist_km"], 1),
        "return_event_mjd": round(best["mjd"], 2),
        "valid_return_event": bool(check["valid_return_event"]),
        "return_vinf_kms": check["return_vinf_kms"] if check["valid_return_event"] else None,
        "return_braking_proxy_kms": (
            round(max(0.0, float(check["return_vinf_kms"]) - 15.0), 4)
            if check["valid_return_event"]
            else None
        ),
        "total_vinf_basis_kms": (
            round(float(traj.v_inf_earth) + max(0.0, float(check["return_vinf_kms"]) - 15.0), 4)
            if check["valid_return_event"]
            else None
        ),
        "event_distance_km": round(best["dist_km"], 1),
        "used_nominal_window": used_nominal_window,
        "fallback_full_window_used": fallback_full_window_used,
        "time_in_event_search_sec": round(coarse_time + refine_time, 4),
        "time_in_coarse_search_sec": round(coarse_time, 4),
        "time_in_refine_search_sec": round(refine_time, 4),
        "event_reason": check["reason"],
    }


def _worker(sample: dict[str, Any]) -> dict[str, Any]:
    sample_id = sample["sample_id"]
    t_start = time.perf_counter()
    nominal_return_mjd = sample["nominal_return_mjd"]
    max_runtime_per_sample_sec = sample["max_runtime_per_sample_sec"]
    global _BODY_DATA_CACHE
    if _BODY_DATA_CACHE is None:
        _BODY_DATA_CACHE = fetch_sem_vectors(use_cache=True)
    body_data = _BODY_DATA_CACHE

    params = DesignParams(
        t0_mjd=sample["t0_mjd"],
        r_m=sample["r_m_km"],
        side=sample["side"],
        r_p=sample["r_p_au"] * AU_KM,
    )

    try:
        prop_start = time.perf_counter()
        traj = solve_trajectory(params, body_data, verbose=False)
        time_in_propagation = time.perf_counter() - prop_start

        if time.perf_counter() - t_start > max_runtime_per_sample_sec:
            return {
                "sample_id": sample_id,
                "classification": "TIMEOUT_NO_FORMAL_RESULT",
                "success": False,
                "valid_return_event": False,
                "reason": "timeout_before_event_search",
                "t0_mjd": round(sample["t0_mjd"], 6),
                "r_m_km": round(sample["r_m_km"], 3),
                "rp_target_au": round(sample["r_p_au"], 6),
                "side": sample["side"],
                "nominal_return_mjd": round(nominal_return_mjd, 6),
                "time_total_sec": round(time.perf_counter() - t_start, 4),
                "time_in_propagation_sec": round(time_in_propagation, 4),
                "time_in_event_search_sec": 0.0,
            }

        event = _search_return_event(traj, body_data, sample["t0_mjd"], nominal_return_mjd)
        if time.perf_counter() - t_start > max_runtime_per_sample_sec:
            return {
                "sample_id": sample_id,
                "classification": "TIMEOUT_NO_FORMAL_RESULT",
                "success": False,
                "valid_return_event": False,
                "reason": "timeout_after_event_search",
                "t0_mjd": round(sample["t0_mjd"], 6),
                "r_m_km": round(sample["r_m_km"], 3),
                "rp_target_au": round(sample["r_p_au"], 6),
                "side": sample["side"],
                "nominal_return_mjd": round(nominal_return_mjd, 6),
                "time_total_sec": round(time.perf_counter() - t_start, 4),
                "time_in_propagation_sec": round(time_in_propagation, 4),
                "time_in_event_search_sec": event["time_in_event_search_sec"],
            }

        classification = "VALID_RETURN_EVENT" if event["valid_return_event"] else "INVALID_NO_FORMAL_RESULT"
        return {
            "sample_id": sample_id,
            "classification": classification,
            "success": True,
            "t0_mjd": round(sample["t0_mjd"], 6),
            "r_m_km": round(sample["r_m_km"], 3),
            "rp_target_au": round(sample["r_p_au"], 6),
            "side": sample["side"],
            "nominal_return_mjd": round(nominal_return_mjd, 6),
            "perihelion_achieved_au": round(traj.r_p_achieved_km / AU_KM, 6),
            "departure_vinf_kms": round(float(traj.v_inf_earth), 4),
            "valid_return_event": event["valid_return_event"],
            "event_distance_km": event["event_distance_km"],
            "coarse_min_distance_km": event["coarse_min_distance_km"],
            "refined_min_distance_km": event["refined_min_distance_km"],
            "return_event_mjd": event["return_event_mjd"],
            "return_vinf_kms": event["return_vinf_kms"],
            "return_braking_proxy_kms": event["return_braking_proxy_kms"],
            "total_vinf_basis_kms": event["total_vinf_basis_kms"],
            "used_nominal_window": event["used_nominal_window"],
            "fallback_full_window_used": event["fallback_full_window_used"],
            "event_reason": event["event_reason"],
            "time_total_sec": round(time.perf_counter() - t_start, 4),
            "time_in_propagation_sec": round(time_in_propagation, 4),
            "time_in_event_search_sec": event["time_in_event_search_sec"],
        }
    except Exception as exc:
        return {
            "sample_id": sample_id,
            "classification": "INVALID_NO_FORMAL_RESULT",
            "success": False,
            "valid_return_event": False,
            "reason": f"exception:{type(exc).__name__}",
            "t0_mjd": round(sample["t0_mjd"], 6),
            "r_m_km": round(sample["r_m_km"], 3),
            "rp_target_au": round(sample["r_p_au"], 6),
            "side": sample["side"],
            "nominal_return_mjd": round(nominal_return_mjd, 6),
            "time_total_sec": round(time.perf_counter() - t_start, 4),
            "time_in_propagation_sec": 0.0,
            "time_in_event_search_sec": 0.0,
        }


def _build_samples(
    n: int,
    seed: int,
    nominal_return_mjd: float,
    max_runtime_per_sample_sec: float,
    reference_candidate: dict[str, Any],
) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    samples = []
    for sample_id in range(n):
        samples.append(
            {
                "sample_id": sample_id,
                "t0_mjd": float(reference_candidate["t0_mjd"]) + float(rng.normal(0.0, 1.0)),
                "r_m_km": float(reference_candidate["r_m_km"]) + float(rng.normal(0.0, 500.0)),
                "r_p_au": float(reference_candidate["target_rp_AU"]) + float(rng.normal(0.0, 0.005)),
                "side": reference_candidate["side"],
                "nominal_return_mjd": nominal_return_mjd,
                "max_runtime_per_sample_sec": max_runtime_per_sample_sec,
            }
        )
    return samples


def _run_pool(samples: list[dict[str, Any]], max_workers: int, max_runtime_sec: float) -> list[dict[str, Any]]:
    start = time.perf_counter()
    results: list[dict[str, Any]] = []
    if max_workers <= 1:
        last_heartbeat = start
        for sample in samples:
            if time.perf_counter() - start > max_runtime_sec:
                results.append(
                    {
                        "sample_id": sample["sample_id"],
                        "classification": "TIMEOUT_NO_FORMAL_RESULT",
                        "success": False,
                        "valid_return_event": False,
                        "reason": "global_runtime_exceeded_before_sample",
                        "t0_mjd": round(sample["t0_mjd"], 6),
                        "r_m_km": round(sample["r_m_km"], 3),
                        "rp_target_au": round(sample["r_p_au"], 6),
                        "side": sample["side"],
                        "nominal_return_mjd": round(sample["nominal_return_mjd"], 6),
                        "time_total_sec": 0.0,
                        "time_in_propagation_sec": 0.0,
                        "time_in_event_search_sec": 0.0,
                    }
                )
                continue
            results.append(_worker(sample))
            done = len(results)
            now = time.perf_counter()
            if done % 10 == 0 or done == len(samples) or now - last_heartbeat >= 60.0:
                print(f"  {_progress_line(done, len(samples), start, 'serial')}", flush=True)
                last_heartbeat = now
        return sorted(results, key=lambda item: item["sample_id"])

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_worker, sample) for sample in samples]
        future_to_sample = {future: sample for sample, future in zip(samples, futures, strict=False)}
        last_heartbeat = start
        done = 0
        for future in as_completed(future_to_sample):
            sample = future_to_sample[future]
            if time.perf_counter() - start > max_runtime_sec:
                results.append(
                    {
                        "sample_id": sample["sample_id"],
                        "classification": "TIMEOUT_NO_FORMAL_RESULT",
                        "success": False,
                        "valid_return_event": False,
                        "reason": "global_runtime_exceeded",
                        "t0_mjd": round(sample["t0_mjd"], 6),
                        "r_m_km": round(sample["r_m_km"], 3),
                        "rp_target_au": round(sample["r_p_au"], 6),
                        "side": sample["side"],
                        "nominal_return_mjd": round(sample["nominal_return_mjd"], 6),
                        "time_total_sec": 0.0,
                        "time_in_propagation_sec": 0.0,
                        "time_in_event_search_sec": 0.0,
                    }
                )
                continue
            results.append(future.result())
            done += 1
            now = time.perf_counter()
            if done % 10 == 0 or done == len(samples) or now - last_heartbeat >= 60.0:
                print(f"  {_progress_line(done, len(samples), start, 'pool')}", flush=True)
                last_heartbeat = now
    return sorted(results, key=lambda item: item["sample_id"])


def _profile(results: list[dict[str, Any]], time_total_sec: float) -> dict[str, Any]:
    valid = [r for r in results if r.get("valid_return_event")]
    per_sample = [float(r.get("time_total_sec", 0.0)) for r in results]
    prop_times = [float(r.get("time_in_propagation_sec", 0.0)) for r in results]
    event_times = [float(r.get("time_in_event_search_sec", 0.0)) for r in results]
    slowest = max(results, key=lambda r: float(r.get("time_total_sec", 0.0))) if results else None
    return {
        "samples_total": len(results),
        "samples_valid": len(valid),
        "time_total_sec": round(time_total_sec, 4),
        "time_per_sample_mean_sec": round(float(statistics.fmean(per_sample)) if per_sample else 0.0, 4),
        "time_per_sample_p95_sec": round(float(np.percentile(per_sample, 95)) if per_sample else 0.0, 4),
        "time_in_propagation_sec": round(sum(prop_times), 4),
        "time_in_event_search_sec": round(sum(event_times), 4),
        "time_in_json_write_sec": 0.0,
        "slowest_sample_id": None if slowest is None else slowest.get("sample_id"),
        "slowest_sample_reason": None if slowest is None else slowest.get("reason", slowest.get("event_reason")),
        "bottleneck_guess": "event_search" if sum(event_times) > sum(prop_times) else "trajectory_propagation",
    }


def _summarize(
    results: list[dict[str, Any]],
    *,
    n: int,
    seed: int,
    smoke: bool,
    profile: dict[str, Any],
    reference_candidate: dict[str, Any],
    sample_rows_path: Path | None,
    timeout_manifest_path: Path | None,
) -> dict[str, Any]:
    valid = [r for r in results if r.get("valid_return_event")]
    invalid = [r for r in results if r.get("classification") == "INVALID_NO_FORMAL_RESULT"]
    timeouts = [r for r in results if r.get("classification") == "TIMEOUT_NO_FORMAL_RESULT"]
    valid_return_vinf = [float(r["return_vinf_kms"]) for r in valid if r.get("return_vinf_kms") is not None]
    valid_total = [float(r["total_vinf_basis_kms"]) for r in valid if r.get("total_vinf_basis_kms") is not None]
    valid_event_dist = [float(r["event_distance_km"]) for r in valid if r.get("event_distance_km") is not None]

    classification = (
        "SMOKE_SEMANTICS_RESULT"
        if smoke
        else "FULL_MC_ACTUAL_RESULT"
        if n >= 200
        else "SMOKE_PASS_FULL_PENDING"
    )
    if not smoke and n < 200:
        classification = "SMOKE_PASS_FULL_PENDING"

    timeout_reason_breakdown: dict[str, int] = {}
    for row in timeouts:
        reason = str(row.get("reason") or "unknown")
        timeout_reason_breakdown[reason] = timeout_reason_breakdown.get(reason, 0) + 1

    return {
        "task": "M7 extended Monte Carlo",
        "classification": classification,
        "n": n,
        "seed": seed,
        "reference_candidate": reference_candidate,
        "valid_return_count": len(valid),
        "invalid_count": len(invalid),
        "timeout_count": len(timeouts),
        "valid_return_rate": round(len(valid) / n, 6) if n > 0 else 0.0,
        "return_vinf_valid_only": _quantiles(valid_return_vinf),
        "total_vinf_basis_valid_only": _quantiles(valid_total),
        "event_distance_km_valid_only": (
            {
                "max": round(max(valid_event_dist), 4),
                "p95": round(float(np.percentile(valid_event_dist, 95)), 4),
            }
            if valid_event_dist
            else None
        ),
        "old_invalid_return_vinf_guard": True,
        "event_semantics": {
            "return_vinf_defined_only_at_earth_return": True,
            "earth_return_threshold_km": EARTH_RETURN_THRESHOLD_KM,
            "nominal_window_half_width_days": NOMINAL_WINDOW_HALF_WIDTH_DAYS,
            "fallback_window_half_width_days": FALLBACK_WINDOW_HALF_WIDTH_DAYS,
            "coarse_step_days": COARSE_STEP_DAYS,
            "coarse_dt_internal_s": COARSE_DT_INTERNAL_S,
            "refine_step_s": REFINE_STEP_S,
        },
        "profile": profile,
        "sample_rows_saved": sample_rows_path is not None,
        "sample_rows_file": None if sample_rows_path is None else str(sample_rows_path.relative_to(_REPO)).replace("\\", "/"),
        "timeout_replay_manifest_file": None if timeout_manifest_path is None else str(timeout_manifest_path.relative_to(_REPO)).replace("\\", "/"),
        "timeout_reason_breakdown": dict(sorted(timeout_reason_breakdown.items())),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> float:
    path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return time.perf_counter() - t0


def _write_sample_rows_json(path: Path, results: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "task": "M7 Monte Carlo sample rows",
        "count": len(results),
        "results": results,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_sample_rows_csv(path: Path, results: list[dict[str, Any]]) -> None:
    if not results:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)


def _write_timeout_replay_manifest(path: Path, results: list[dict[str, Any]], summary_output: Path) -> None:
    timeout_rows = [row for row in results if row.get("classification") == "TIMEOUT_NO_FORMAL_RESULT"]
    summary_output = summary_output.resolve()
    manifest = {
        "task": "M7 timeout replay manifest",
        "source_summary_file": str(summary_output.relative_to(_REPO)).replace("\\", "/"),
        "timeout_count": len(timeout_rows),
        "samples": [
            {
                "sample_id": row["sample_id"],
                "t0_mjd": row.get("t0_mjd"),
                "r_m_km": row.get("r_m_km"),
                "rp_target_au": row.get("rp_target_au"),
                "side": row.get("side"),
                "nominal_return_mjd": row.get("nominal_return_mjd"),
                "reason": row.get("reason"),
            }
            for row in timeout_rows
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def _progress_line(done: int, total: int, started: float, label: str) -> str:
    elapsed = time.perf_counter() - started
    pct = (done / total * 100.0) if total else 100.0
    rate = done / elapsed if elapsed > 0 else 0.0
    eta = (total - done) / rate if rate > 0 else float("inf")
    bar_len = 24
    filled = int(round(bar_len * done / total)) if total else bar_len
    bar = "#" * min(filled, bar_len) + "-" * max(bar_len - filled, 0)
    eta_text = "unknown" if not (eta < float("inf")) else time.strftime("%H:%M:%S", time.gmtime(max(0.0, eta)))
    elapsed_text = time.strftime("%H:%M:%S", time.gmtime(max(0.0, elapsed)))
    return f"[{bar}] {done}/{total} {pct:5.1f}% elapsed={elapsed_text} eta={eta_text} {label}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=DEFAULT_N_FULL)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    parser.add_argument("--max-runtime-sec", type=float, default=DEFAULT_MAX_RUNTIME_SEC)
    parser.add_argument("--max-runtime-per-sample-sec", type=float, default=DEFAULT_MAX_RUNTIME_PER_SAMPLE_SEC)
    parser.add_argument("--output", type=str, default=str(RESULTS / "m7_extended_monte_carlo.json"))
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--save-sample-rows", action="store_true")
    parser.add_argument("--sample-rows-output", type=str, default=str(RESULTS / "m7_extended_monte_carlo_samples.json"))
    parser.add_argument("--sample-rows-csv-output", type=str, default=str(RESULTS / "m7_extended_monte_carlo_samples.csv"))
    parser.add_argument("--timeout-replay-manifest-output", type=str, default=str(RESULTS / "m7_timeout_replay_manifest.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    nominal_return_mjd = _load_nominal_return_mjd()
    reference_candidate = _load_reference_candidate()

    n = args.n if not args.smoke else min(args.n, DEFAULT_N_SMOKE)
    smoke = bool(args.smoke)
    output = Path(args.output).resolve()
    start = time.perf_counter()
    samples = _build_samples(
        n=n,
        seed=args.seed,
        nominal_return_mjd=nominal_return_mjd,
        max_runtime_per_sample_sec=args.max_runtime_per_sample_sec,
        reference_candidate=reference_candidate,
    )
    results = _run_pool(samples, max_workers=args.max_workers, max_runtime_sec=args.max_runtime_sec)
    time_total_sec = time.perf_counter() - start
    profile = _profile(results, time_total_sec)

    sample_rows_path = Path(args.sample_rows_output).resolve() if args.save_sample_rows else None
    sample_rows_csv_path = Path(args.sample_rows_csv_output).resolve() if args.save_sample_rows else None
    timeout_manifest_path = Path(args.timeout_replay_manifest_output).resolve() if args.save_sample_rows else None

    summary = _summarize(
        results,
        n=n,
        seed=args.seed,
        smoke=smoke,
        profile=profile,
        reference_candidate=reference_candidate,
        sample_rows_path=sample_rows_path,
        timeout_manifest_path=timeout_manifest_path,
    )

    if args.save_sample_rows:
        _write_sample_rows_json(sample_rows_path, results)
        _write_sample_rows_csv(sample_rows_csv_path, results)
        _write_timeout_replay_manifest(timeout_manifest_path, results, output)

    json_write_sec = _write_json(output, summary)
    summary["profile"]["time_in_json_write_sec"] = round(json_write_sec, 4)
    _write_json(output, summary)

    print("=" * 66)
    print("M7 extended Monte Carlo")
    print("=" * 66)
    print(f"n={n}, seed={args.seed}, smoke={smoke}, max_workers={args.max_workers}")
    print(f"valid_returns={summary['valid_return_count']}/{n}, invalid={summary['invalid_count']}, timeout={summary['timeout_count']}")
    print(f"time_total_sec={summary['profile']['time_total_sec']}")
    print(f"time_per_sample_mean_sec={summary['profile']['time_per_sample_mean_sec']}")
    print(f"bottleneck={summary['profile']['bottleneck_guess']}")
    print(f"sample_rows_saved={summary['sample_rows_saved']}")
    print(f"Saved: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
