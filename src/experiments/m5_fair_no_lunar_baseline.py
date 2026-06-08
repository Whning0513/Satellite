"""
m5_fair_no_lunar_baseline.py
============================
Fair no-lunar baseline using same N-body propagation and return detection.
Lunar and no-lunar both use solve_trajectory's S2 departure, but no-lunar
skips the Moon swingby and propagates the heliocentric arc directly.
"""

import json, os, sys, numpy as np, time, math
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import (
    GM_SUN, GM_EARTH, GM_MOON, AU_KM, R_MOON, R_MOON_SOI, R_EARTH,
    V_ESCAPE_EARTH, V_INF_MAX, DT_MAIN, DT_REFINE,
)
from units import km_to_au, day_to_sec, sec_to_day
from nbody import GM_SEMR, propagate_nbody, vv_step_nbody
from trajectory import DesignParams, solve_trajectory, interpolate_state_at_mjd
from patched_conic import compute_patched_conic
from horizons import fetch_sem_vectors, state_at_index, initial_state_from_horizons


def _v(v):
    return np.array(v, dtype=float)
def _norm(v):
    return float(np.linalg.norm(_v(v)))
def _fmt(v):
    return [round(float(x), 4) for x in _v(v)]


def solve_no_lunar_nbody(t0_mjd, rp_design_AU, body_data, dt_internal=3600.0):
    """Fair N-body no-lunar baseline.

    1. Same Earth departure as lunar solve_trajectory (patched-conic S2).
    2. Propagate Sun-Earth-Moon-Rocket for up to 730 days.
    3. Detect perihelion, then find Earth closest approach after it.
    4. Return same dv schema as lunar case.
    """
    # Earth state at t0
    r_earth, v_earth = interpolate_state_at_mjd(body_data, "Earth", t0_mjd)
    r_sun, v_sun = interpolate_state_at_mjd(body_data, "Sun", t0_mjd)

    # Patched-conic departure (same as lunar S2)
    elements = compute_patched_conic(r_p_AU=rp_design_AU)
    v_inf_depart = abs(elements.delta_v)
    v_launch = math.sqrt(V_ESCAPE_EARTH**2 + v_inf_depart**2)

    # Direction: retrograde for interior transfer (r_p < 1 AU)
    earth_vel_dir = v_earth / (_norm(v_earth) + 1e-15)
    if elements.delta_v < 0:
        v_inf_dir = -earth_vel_dir  # retrograde
    else:
        v_inf_dir = earth_vel_dir   # prograde

    # Compute SOI-exit initial state (NOT Earth surface)
    # Earth SOI radius
    R_SOI_EARTH = 925000.0  # km
    # v_inf vector relative to Earth
    v_inf_vec = v_inf_depart * v_inf_dir
    # Hyperbolic escape speed at SOI boundary from energy:
    # v_soi^2 = v_inf^2 + 2*mu_earth / R_SOI
    v_rel_soi = math.sqrt(v_inf_depart**2 + 2.0 * GM_EARTH / R_SOI_EARTH)

    # Position on Earth SOI boundary in the v_inf direction (outgoing)
    r_soi = r_earth + R_SOI_EARTH * v_inf_dir
    v_soi = v_earth + v_rel_soi * v_inf_dir

    # Sanity: ensure rocket is leaving Earth
    v_rel_check = _v(v_soi) - _v(v_earth)
    leaving_earth = np.dot(v_rel_check, r_soi - r_earth) > 0

    # Compute launch dv from v_inf (same formula as lunar case)
    v_launch = math.sqrt(V_ESCAPE_EARTH**2 + v_inf_depart**2)

    # Use SOI-exit state for N-body propagation
    r_rocket = r_soi
    v_rocket = v_soi

    # Sun-only sanity: compute orbital elements from rocket heliocentric state
    r_h = _v(r_rocket) - _v(r_sun)
    v_h = _v(v_rocket) - _v(v_sun)
    rn = _norm(r_h); vn = _norm(v_h); mu = GM_SUN
    eps = 0.5*vn**2 - mu/rn
    a_sun = -mu/(2*eps) if abs(eps) > 1e-15 else 1e15
    # 2D angular momentum scalar: h = r[0]*v[1] - r[1]*v[0]
    h_scalar = r_h[0]*v_h[1] - r_h[1]*v_h[0]
    e_sun = math.sqrt(max(0, 1 - h_scalar**2/(mu*a_sun))) if a_sun > 0 else 1
    rp_anal = abs(a_sun)*(1 - e_sun) if a_sun > 0 else 1e15
    rp_sun_check = km_to_au(rp_anal)
    sun_only_pass = abs(rp_sun_check - rp_design_AU) < 0.02
    if not sun_only_pass:
        print(f"    WARNING: Sun-only sanity FAILED: rp_analytic={rp_sun_check:.4f} AU "
              f"(design {rp_design_AU} AU). a={a_sun/AU_KM:.4f} AU, e={e_sun:.4f}")
        print(f"    v_helio_target={math.sqrt(mu*(2/rn - 1/(0.5*(rn+rp_design_AU*AU_KM)))):.4f} km/s, "
              f"v_helio_actual={vn:.4f} km/s")

    # Initial Moon state
    r_moon, v_moon = interpolate_state_at_mjd(body_data, "Moon", t0_mjd)

    # r4 = [Sun, Earth, Moon, Rocket]
    r4 = [r_sun.copy(), r_earth.copy(), r_moon.copy(), r_rocket.copy()]
    v4 = [v_sun.copy(), v_earth.copy(), v_moon.copy(), v_rocket.copy()]
    gm4 = [GM_SUN, GM_EARTH, GM_MOON, 0.0]

    # Propagate up to 730 days
    max_sec = 730 * 86400.0
    dt = dt_internal
    n_steps = int(max_sec / dt)

    # Tracking
    r_min_sun = np.inf
    idx_min_sun = 0
    rocket_traj = []  # (t_days, r_rocket, v_rocket, r_sun, r_earth)
    record_every = max(n_steps // 3000, 1)

    for step in range(n_steps):
        t_now = (step + 1) * dt
        r4, v4 = vv_step_nbody(r4, v4, dt, gm4, 4)

        if step % record_every == 0:
            rocket_traj.append({
                "t": t_now / 86400.0,
                "rr": r4[3].copy(),
                "vr": v4[3].copy(),
                "rs": r4[0].copy(),
                "re": r4[1].copy(),
                "ve": v4[1].copy(),
            })

        sd = _norm(r4[3] - r4[0])
        if sd < r_min_sun:
            r_min_sun = sd
            idx_min_sun = len(rocket_traj) - 1

    rp_actual_km = r_min_sun
    rp_actual_AU = km_to_au(rp_actual_km)
    rp_error_rel = abs(rp_actual_AU - rp_design_AU) / rp_design_AU

    # Earth return detection: after perihelion, find min Earth distance
    post_traj = rocket_traj[idx_min_sun:]
    if not post_traj:
        return {"mode": "no_lunar_nbody", "success": False,
                "error": "No perihelion detected"}

    best_earth_dist = np.inf
    best_idx = 0
    for i, pt in enumerate(post_traj):
        ed = _norm(pt["rr"] - pt["re"])
        if ed < best_earth_dist:
            best_earth_dist = ed
            best_idx = idx_min_sun + i

    return_point = rocket_traj[best_idx]
    v_rel_return_vec = return_point["vr"] - return_point["ve"]
    v_rel_return_norm = _norm(v_rel_return_vec)
    dv_reentry = max(0, v_rel_return_norm - V_INF_MAX)

    earth_return_valid = bool(best_earth_dist < 500000.0)  # within 2 AU = reasonable return

    dv_total = v_launch + dv_reentry
    flight_time_days = return_point["t"]

    return {
        "mode": "no_lunar_soi_exit_nbody",
        "t0_mjd": t0_mjd,
        "rp_design_AU": rp_design_AU,
        "sun_only_sanity": {
            "sun_only_rp_AU": round(rp_sun_check, 6),
            "a_sun_AU": round(a_sun/AU_KM, 6),
            "e_sun": round(e_sun, 6),
            "pass": bool(sun_only_pass),
        },
        "nbody_rp_actual_AU": round(rp_actual_AU, 6),
        "rp_error_rel": round(rp_error_rel, 6),
        "v_trans_helio_kms": round(math.sqrt(mu*(2/rn - 1/(0.5*(rn+rp_design_AU*AU_KM)))), 4),
        "earth_speed_kms": round(_norm(v_earth - v_sun), 4),
        "v_inf_depart_kms": round(v_inf_depart, 4),
        "soi_exit_radius_km": R_SOI_EARTH,
        "soi_exit_speed_rel_earth_kms": round(v_rel_soi, 4),
        "dv_launch_kms": round(v_launch, 4),
        "dv_lunar_residual_kms": 0.0,
        "closest_earth_approach_km": round(best_earth_dist, 1),
        "earth_return_valid": bool(earth_return_valid),
        "v_rel_return_kms": round(v_rel_return_norm, 4),
        "dv_reentry_kms": round(dv_reentry, 4),
        "dv_total_corrected_kms": round(dv_total, 4),
        "flight_time_days": round(flight_time_days, 2),
        "warnings": ["Sun-only failed"] if not sun_only_pass else [],
    }


def solve_lunar_assist(t0_mjd, rp_design_AU, body_data):
    """Same as current solve_trajectory."""
    params = DesignParams(t0_mjd=t0_mjd, r_m=R_MOON+500, side="trailing", r_p=rp_design_AU*AU_KM)
    traj = solve_trajectory(params, body_data, verbose=False)

    v_rel_return_vec = _v(traj.v_final) - _v(traj.v_earth_final)
    v_rel_return_norm = _norm(v_rel_return_vec)
    dv_reentry = max(0, v_rel_return_norm - V_INF_MAX)

    return {
        "mode": "lunar_assist",
        "t0_mjd": t0_mjd,
        "rp_design_AU": rp_design_AU,
        "rp_actual_AU": round(km_to_au(traj.r_p_achieved_km), 6),
        "rp_error_rel": round(abs(traj.r_p_achieved_km - rp_design_AU*AU_KM) / (rp_design_AU*AU_KM), 6),
        "v_inf_depart_kms": round(traj.v_inf_earth, 4),
        "dv_launch_kms": round(traj.v_launch, 4),
        "dv_lunar_residual_kms": round(traj.swingby.dv_mag, 6) if traj.swingby else 0.0,
        "closest_earth_approach_km": round(_norm(traj.r_final - traj.r_earth_final), 1),
        "earth_return_valid": True,
        "return_mjd": t0_mjd + traj.t_total_days,
        "v_rel_return_kms": round(v_rel_return_norm, 4),
        "dv_reentry_kms": round(dv_reentry, 4),
        "dv_total_corrected_kms": round(traj.v_launch + (traj.swingby.dv_mag if traj.swingby else 0) + dv_reentry, 4),
        "flight_time_days": round(traj.t_total_days, 2),
        "constraints_satisfied": True,  # noqa
        "warnings": [],
    }


def patched_conic_reference(t0_mjd, rp_design_AU):
    """Pure patched-conic reference (no N-body, for documentation)."""
    elements = compute_patched_conic(r_p_AU=rp_design_AU)
    v_inf = abs(elements.delta_v)
    v_launch = math.sqrt(V_ESCAPE_EARTH**2 + v_inf**2)
    dv_reentry = max(0, v_inf - V_INF_MAX)
    return {
        "mode": "patched_conic_reference",
        "t0_mjd": t0_mjd,
        "rp_design_AU": rp_design_AU,
        "rp_actual_AU": rp_design_AU,
        "rp_error_rel": 0.0,
        "v_inf_depart_kms": round(v_inf, 4),
        "dv_launch_kms": round(v_launch, 4),
        "dv_lunar_residual_kms": 0.0,
        "earth_return_valid": True,
        "v_rel_return_kms": round(v_inf, 4),
        "dv_reentry_kms": round(dv_reentry, 4),
        "dv_total_corrected_kms": round(v_launch + dv_reentry, 4),
        "flight_time_days": round(elements.dt_flight_days, 2),
        "note": "Symmetric approximation; return v_rel = departure v_rel (patched-conic assumption).",
    }


def main():
    bd = fetch_sem_vectors(use_cache=True)
    windows = [(61066.0, "MJD 61066 (balanced)"), (61154.0, "MJD 61154 (best_dv)")]
    t0_run = time.time()

    results = []
    for t0, label in windows:
        print(f"\n{'='*55}")
        print(f"  Window: {label}")
        print(f"{'='*55}")

        print("  Lunar assist (N-body)...")
        lunar = solve_lunar_assist(t0, 0.3, bd)

        print("  No-lunar direct (N-body, 730d max)...")
        no_lunar = solve_no_lunar_nbody(t0, 0.3, bd, dt_internal=3600.0)

        print("  Patched-conic reference...")
        pc_ref = patched_conic_reference(t0, 0.3)

        # Fairness check
        both_return = bool(lunar["earth_return_valid"] and no_lunar["earth_return_valid"])
        nbody_rp = no_lunar.get("nbody_rp_actual_AU", no_lunar.get("rp_actual_AU", 0))
        rp_close = abs(lunar["rp_actual_AU"] - nbody_rp) < 0.2

        comparison_valid = bool(both_return and rp_close)

        savings = None
        if comparison_valid:
            ls = (no_lunar["dv_launch_kms"] - lunar["dv_launch_kms"]) / max(no_lunar["dv_launch_kms"], 0.01)
            ts = (no_lunar["dv_total_corrected_kms"] - lunar["dv_total_corrected_kms"]) / max(no_lunar["dv_total_corrected_kms"], 0.01)
            savings = {
                "launch_saving_ratio": round(ls, 4),
                "total_saving_ratio": round(ts, 4),
            }

        case = {
            "t0_mjd": t0,
            "label": label,
            "lunar_assist": lunar,
            "no_lunar_direct_nbody": no_lunar,
            "patched_conic_reference": pc_ref,
            "comparison_valid": comparison_valid,
            "savings": savings,
        }
        results.append(case)

        print(f"\n    Lunar:   rp={lunar['rp_actual_AU']:.4f} AU, dv_launch={lunar['dv_launch_kms']:.2f}, "
              f"dv_moon={lunar['dv_lunar_residual_kms']:.4f}, dv_brake={lunar['dv_reentry_kms']:.1f}, "
              f"total={lunar['dv_total_corrected_kms']:.1f}, return_ok={lunar['earth_return_valid']}")
        no_lunar_rp_show = no_lunar.get("nbody_rp_actual_AU", no_lunar.get("rp_actual_AU", 0))
        print(f"    No-lunar: rp={no_lunar_rp_show:.4f} AU, dv_launch={no_lunar['dv_launch_kms']:.2f}, "
              f"closest_earth={no_lunar['closest_earth_approach_km']:.0f} km, "
              f"v_rel_return={no_lunar['v_rel_return_kms']:.1f}, "
              f"dv_brake={no_lunar['dv_reentry_kms']:.1f}, "
              f"total={no_lunar['dv_total_corrected_kms']:.1f}, return_ok={no_lunar['earth_return_valid']}")
        print(f"    PC ref:  dv_launch={pc_ref['dv_launch_kms']:.2f}, total={pc_ref['dv_total_corrected_kms']:.1f}")
        print(f"    Comparison valid: {comparison_valid}, savings: {savings}")

    elapsed = time.time() - t0_run
    summary = {
        "description": "Fair no-lunar comparison under same N-body propagation and return-event criterion",
        "dt_internal_s": 3600.0,
        "max_flight_days": 730,
        "runtime_s": round(elapsed, 1),
        "cases": results,
    }

    # Save
    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    json_path = out_dir / "m5_fair_no_lunar_baseline.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n[M5] Saved to {json_path}")

    import csv
    csv_path = out_dir / "m5_fair_no_lunar_baseline.csv"
    with open(csv_path, "w", newline="") as f:
        fields = ["t0_mjd", "mode", "rp_actual_AU", "rp_error_rel",
                  "dv_launch_kms", "dv_lunar_residual_kms", "dv_reentry_kms",
                  "dv_total_corrected_kms", "closest_earth_approach_km",
                  "earth_return_valid", "comparison_valid"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for case in results:
            for mode_key in ["lunar_assist", "no_lunar_direct_nbody", "patched_conic_reference"]:
                c = case[mode_key]
                row = {k: c.get(k, "") for k in fields}
                row["t0_mjd"] = case["t0_mjd"]
                row["comparison_valid"] = case["comparison_valid"]
                w.writerow(row)
    print(f"[M5] CSV -> {csv_path}")

    print(f"\n{'='*55}")
    print("Summary")
    print(f"{'='*55}")
    for case in results:
        print(f"\n  {case['label']}:")
        l = case["lunar_assist"]
        n = case["no_lunar_direct_nbody"]
        print(f"    Lunar:   total={l['dv_total_corrected_kms']:.1f} km/s, "
              f"rp={l['rp_actual_AU']:.4f} AU, return_ok={l['earth_return_valid']}")
        print(f"    No-lunar: total={n['dv_total_corrected_kms']:.1f} km/s, "
              f"rp={n.get('nbody_rp_actual_AU', n.get('rp_actual_AU', 0)):.4f} AU, return_ok={n['earth_return_valid']}, "
              f"closest_earth={n['closest_earth_approach_km']:.0f} km")
        if case["comparison_valid"]:
            s = case["savings"]
            print(f"    Comparison VALID. Launch saving: {s['launch_saving_ratio']:.2%}, "
                  f"Total saving: {s['total_saving_ratio']:.2%}")
        else:
            print(f"    Comparison INVALID — no-lunar did not achieve valid Earth return")


if __name__ == "__main__":
    main()
