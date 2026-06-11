"""
m7_monte_carlo_extended.py
===========================
Extends M7 Monte Carlo from 20 to 200 samples for better statistical power.

The reference trajectory must stay aligned with the currently validated
M5 Earth-return candidate instead of the obsolete 61066 half-trajectory.
This script therefore uses the verified fixed-date lunar solution:
  t0 = 61037.0, side = trailing, r_m = 1837.4 km, r_p ~= 0.3 AU.
"""

import argparse
import math
import json, os, sys, time
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import AU_KM, GM_SUN, GM_EARTH, GM_MOON
from trajectory import solve_trajectory, DesignParams, interpolate_state_at_mjd
from horizons import fetch_sem_vectors
from nbody import propagate_nbody
from event_semantics import compute_earth_return_vinf


M5_VALID_T0 = 61037.0
M5_VALID_RM_KM = 1837.4
M5_VALID_SIDE = "trailing"
M5_VALID_RP_AU = 0.3
EARTH_RETURN_THRESHOLD_KM = 1.5e6
MAX_EXTRA_DAYS = 360
COARSE_STEP_DAYS = 2.0
COARSE_DT_INTERNAL_S = 10800.0
REFINE_WINDOW_DAYS = 3.0
REFINE_STEP_S = 3600.0
DEFAULT_SAMPLES = 200


def _summary(values):
    if len(values) == 0:
        return None
    arr = np.asarray(values, dtype=float)
    return {
        "mean": round(float(arr.mean()), 6),
        "std": round(float(arr.std()), 6),
        "p5": round(float(np.percentile(arr, 5)), 6),
        "p50": round(float(np.percentile(arr, 50)), 6),
        "p95": round(float(np.percentile(arr, 95)), 6),
    }


def _clone_state(r_list, v_list):
    return [ri.copy() for ri in r_list], [vi.copy() for vi in v_list]


def _sync_earth_moon(body_data, mjd, r_state, v_state):
    r_earth, v_earth = interpolate_state_at_mjd(body_data, "Earth", mjd)
    r_state[1] = r_earth.copy()
    v_state[1] = v_earth.copy()
    r_moon, v_moon = interpolate_state_at_mjd(body_data, "Moon", mjd)
    r_state[2] = r_moon.copy()
    v_state[2] = v_moon.copy()


def _update_best(best, mjd, r_state, v_state):
    dist_earth = float(np.linalg.norm(r_state[3] - r_state[1]))
    if dist_earth < best["dist_km"]:
        best["dist_km"] = dist_earth
        best["mjd"] = mjd
        best["r_sc"] = r_state[3].copy()
        best["v_sc"] = v_state[3].copy()
        best["r_earth"] = r_state[1].copy()
        best["v_earth"] = v_state[1].copy()
    return dist_earth


def _propagate_to_return_event(traj, body_data, launch_mjd, max_extra_days=MAX_EXTRA_DAYS):
    t_end = launch_mjd + traj.t_total_days
    r_sun_end, v_sun_end = interpolate_state_at_mjd(body_data, "Sun", t_end)
    r_moon_end, v_moon_end = interpolate_state_at_mjd(body_data, "Moon", t_end)

    r = [
        r_sun_end.copy(),
        traj.r_earth_final.copy(),
        r_moon_end.copy(),
        traj.r_final.copy(),
    ]
    v = [
        v_sun_end.copy(),
        traj.v_earth_final.copy(),
        v_moon_end.copy(),
        traj.v_final.copy(),
    ]
    gm = [GM_SUN, GM_EARTH, GM_MOON, 0.0]

    best = {
        "dist_km": np.inf,
        "mjd": t_end,
        "r_sc": None,
        "v_sc": None,
        "r_earth": None,
        "v_earth": None,
    }
    _sync_earth_moon(body_data, t_end, r, v)
    _update_best(best, t_end, r, v)

    coarse_states = [(t_end, *_clone_state(r, v))]
    coarse_steps = int(math.ceil(max_extra_days / COARSE_STEP_DAYS))
    step_sec = COARSE_STEP_DAYS * 86400.0
    last_dist = best["dist_km"]

    for step_idx in range(1, coarse_steps + 1):
        r, v = propagate_nbody(
            r, v, step_sec, gm, n_bodies=4, dt_internal=COARSE_DT_INTERNAL_S
        )
        cur_mjd = t_end + step_idx * COARSE_STEP_DAYS
        _sync_earth_moon(body_data, cur_mjd, r, v)
        dist_earth = _update_best(best, cur_mjd, r, v)
        coarse_states.append((cur_mjd, *_clone_state(r, v)))
        if best["dist_km"] < EARTH_RETURN_THRESHOLD_KM and dist_earth > best["dist_km"] * 2.0:
            break
        last_dist = dist_earth

    refine_start_mjd = max(t_end, best["mjd"] - REFINE_WINDOW_DAYS)
    refine_end_mjd = min(t_end + max_extra_days, best["mjd"] + REFINE_WINDOW_DAYS)

    anchor_idx = 0
    for idx, (mjd, _, _) in enumerate(coarse_states):
        if mjd <= refine_start_mjd:
            anchor_idx = idx
        else:
            break

    anchor_mjd, anchor_r, anchor_v = coarse_states[anchor_idx]
    r_refine, v_refine = _clone_state(anchor_r, anchor_v)
    if refine_start_mjd > anchor_mjd:
        r_refine, v_refine = propagate_nbody(
            r_refine,
            v_refine,
            (refine_start_mjd - anchor_mjd) * 86400.0,
            gm,
            n_bodies=4,
            dt_internal=COARSE_DT_INTERNAL_S,
        )
    _sync_earth_moon(body_data, refine_start_mjd, r_refine, v_refine)
    _update_best(best, refine_start_mjd, r_refine, v_refine)

    refine_steps = int(math.ceil((refine_end_mjd - refine_start_mjd) * 86400.0 / REFINE_STEP_S))
    cur_mjd = refine_start_mjd
    for _ in range(refine_steps):
        r_refine, v_refine = propagate_nbody(
            r_refine, v_refine, REFINE_STEP_S, gm, n_bodies=4, dt_internal=REFINE_STEP_S
        )
        cur_mjd += REFINE_STEP_S / 86400.0
        _sync_earth_moon(body_data, cur_mjd, r_refine, v_refine)
        dist_earth = _update_best(best, cur_mjd, r_refine, v_refine)
        if best["dist_km"] < EARTH_RETURN_THRESHOLD_KM and dist_earth > best["dist_km"] * 2.0:
            break

    if best["r_sc"] is None:
        return {
            "valid_return_event": False,
            "closest_earth_km": None,
            "return_epoch_mjd": None,
            "return_vinf_kms": None,
            "return_braking_proxy_kms": None,
            "total_vinf_basis_kms": None,
            "reason": "no_closest_approach_recorded",
        }

    check = compute_earth_return_vinf(best["r_sc"], best["v_sc"], best["r_earth"], best["v_earth"])
    if not check["valid_return_event"]:
        return {
            "valid_return_event": False,
            "closest_earth_km": round(best["dist_km"], 1),
            "return_epoch_mjd": round(best["mjd"], 2),
            "return_vinf_kms": None,
            "return_braking_proxy_kms": None,
            "total_vinf_basis_kms": None,
            "reason": check["reason"],
        }

    return_vinf = float(check["return_vinf_kms"])
    braking = max(0.0, return_vinf - 15.0)
    total_vinf_basis = float(traj.v_inf_earth) + braking
    return {
        "valid_return_event": True,
        "closest_earth_km": round(best["dist_km"], 1),
        "return_epoch_mjd": round(best["mjd"], 2),
        "return_vinf_kms": round(return_vinf, 4),
        "return_braking_proxy_kms": round(braking, 4),
        "total_vinf_basis_kms": round(total_vinf_basis, 4),
        "reason": None,
    }


def run_mc(
    n_samples,
    seed=42,
    t0_base=M5_VALID_T0,
    sigma_t0=1.0,
    sigma_rm=500.0,
    sigma_rp=0.005,
    max_extra_days=MAX_EXTRA_DAYS,
):
    body_data = fetch_sem_vectors(use_cache=True)
    rng = np.random.default_rng(seed)
    results = []
    n_traj_success = 0
    for i in range(n_samples):
        t0 = t0_base + rng.normal(0, sigma_t0)
        rm = M5_VALID_RM_KM + rng.normal(0, sigma_rm)
        rp = M5_VALID_RP_AU * AU_KM + rng.normal(0, sigma_rp * AU_KM)
        params = DesignParams(t0_mjd=t0, r_m=rm, side=M5_VALID_SIDE, r_p=rp)
        try:
            traj = solve_trajectory(params, body_data, verbose=False)
            n_traj_success += 1
            departure_vinf = float(traj.v_inf_earth)
            return_info = _propagate_to_return_event(
                traj, body_data, t0, max_extra_days=max_extra_days
            )
            results.append({
                "sample_id": i,
                "t0_mjd": round(float(t0), 6),
                "r_m_km": round(float(rm), 3),
                "rp_AU": traj.r_p_achieved_km / AU_KM,
                "departure_vinf_kms": departure_vinf,
                "valid_return_event": return_info["valid_return_event"],
                "closest_earth_km": return_info["closest_earth_km"],
                "return_epoch_mjd": return_info["return_epoch_mjd"],
                "return_vinf_kms": return_info["return_vinf_kms"],
                "return_braking_proxy_kms": return_info["return_braking_proxy_kms"],
                "total_vinf_basis_kms": return_info["total_vinf_basis_kms"],
                "return_event_reason": return_info["reason"],
                "success": traj.success,
            })
        except Exception:
            results.append({
                "sample_id": i,
                "t0_mjd": round(float(t0), 6),
                "r_m_km": round(float(rm), 3),
                "rp_AU": 0.0,
                "departure_vinf_kms": 0.0,
                "valid_return_event": False,
                "closest_earth_km": None,
                "return_epoch_mjd": None,
                "return_vinf_kms": None,
                "return_braking_proxy_kms": None,
                "total_vinf_basis_kms": None,
                "return_event_reason": "trajectory_solve_failed",
                "success": False,
            })
    return {"results": results, "n_traj_success": n_traj_success}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--max-extra-days", type=int, default=MAX_EXTRA_DAYS)
    args = parser.parse_args()

    print("=" * 66)
    print("M7: Extended Monte Carlo")
    print("=" * 66)
    print(
        f"Reference candidate: t0={M5_VALID_T0:.0f}, "
        f"r_m={M5_VALID_RM_KM:.1f} km, side={M5_VALID_SIDE}, "
        f"target_rp={M5_VALID_RP_AU:.1f} AU"
    )

    t0 = time.time()
    print(f"\n--- MC: {args.samples} samples ---")
    mc = run_mc(n_samples=args.samples, max_extra_days=args.max_extra_days)
    results = mc["results"]
    elapsed = time.time() - t0

    rp = np.array([r["rp_AU"] for r in results if r["success"]], dtype=float)
    dep = np.array([r["departure_vinf_kms"] for r in results if r["success"]], dtype=float)
    ret = np.array(
        [r["return_vinf_kms"] for r in results if r["valid_return_event"] and r["return_vinf_kms"] is not None],
        dtype=float,
    )
    tot = np.array(
        [r["total_vinf_basis_kms"] for r in results if r["valid_return_event"] and r["total_vinf_basis_kms"] is not None],
        dtype=float,
    )
    n_success = len(rp)
    n_valid_return = sum(1 for r in results if r["valid_return_event"])
    n_invalid_return = args.samples - n_valid_return

    out = {
        "task": "M7 extended Monte Carlo",
        "classification": "ACTUAL_RESULT" if n_valid_return > 0 else "FINITE_SEARCH_NEG",
        "reference_candidate": {
            "source": "validated_M5_lunar_return",
            "t0_mjd": M5_VALID_T0,
            "r_m_km": M5_VALID_RM_KM,
            "side": M5_VALID_SIDE,
            "target_rp_AU": M5_VALID_RP_AU,
        },
        "event_semantics": {
            "return_vinf_defined_only_at_earth_return": True,
            "earth_return_threshold_km": EARTH_RETURN_THRESHOLD_KM,
            "coarse_step_days": COARSE_STEP_DAYS,
            "coarse_dt_internal_s": COARSE_DT_INTERNAL_S,
            "refine_window_days": REFINE_WINDOW_DAYS,
            "refine_step_s": REFINE_STEP_S,
            "max_extra_days": args.max_extra_days,
        },
        "n_samples": args.samples,
        "n_trajectory_success": mc["n_traj_success"],
        "n_success": n_success,
        "n_valid_return": n_valid_return,
        "n_invalid_return": n_invalid_return,
        "seed": 42,
        "elapsed_s": round(elapsed, 1),
        "r_p_AU_successful_trajectory": _summary(rp),
        "departure_vinf_kms_successful_trajectory": _summary(dep),
        "return_vinf_kms_valid_return_only": _summary(ret),
        "total_vinf_basis_kms_valid_return_only": _summary(tot),
    }
    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    jp = out_dir / "m7_monte_carlo_extended.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(
        f"  successful trajectories: {n_success}/{args.samples}, "
        f"valid returns: {n_valid_return}/{args.samples}"
    )
    print(
        f"  r_p(success): mean={out['r_p_AU_successful_trajectory']['mean']:.4f} "
        f"std={out['r_p_AU_successful_trajectory']['std']:.4f}"
    )
    if out["return_vinf_kms_valid_return_only"] is not None:
        print(
            f"  return_vinf(valid-only): mean={out['return_vinf_kms_valid_return_only']['mean']:.2f} "
            f"std={out['return_vinf_kms_valid_return_only']['std']:.4f}"
        )
        print(
            f"  total_vinf_basis(valid-only): mean={out['total_vinf_basis_kms_valid_return_only']['mean']:.2f} "
            f"std={out['total_vinf_basis_kms_valid_return_only']['std']:.4f}"
        )
    else:
        print("  No valid Earth-return events found in this 200-sample perturbation set.")
    print(f"  Time: {elapsed:.0f}s")
    print("\nDone")


if __name__ == "__main__":
    main()
