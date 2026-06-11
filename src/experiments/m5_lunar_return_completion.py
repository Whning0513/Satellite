"""
m5_lunar_return_completion.py
==============================
Completes the M5 lunar-assisted trajectory by adding a return DSM segment.

The original trajectory ends at perihelion (~0.28 AU).  This script:
  1. Identifies the perihelion (or post-perihelion) state.
  2. Tries a Lambert transfer from that state to Earth at a later epoch.
  3. Computes the return DSM delta_v and arrival return_vinf.
  4. Computes the completed total delta_v proxy.
  5. Samples multiple departure states along the post-perihelion arc.

Output: data/results/m5_lunar_return_completion.json
"""

import json, os, sys, time, math
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import GM_SUN, GM_EARTH, GM_MOON, AU_KM, R_MOON
from units import km_to_au, day_to_sec
from trajectory import DesignParams, solve_trajectory, interpolate_state_at_mjd
from lambert import solve_lambert_universal, orbital_elements_from_state
from nbody import propagate_nbody
from event_semantics import compute_earth_return_vinf
from patched_conic import compute_patched_conic
from horizons import fetch_sem_vectors

V_RET_MAX = 15.0
DSM_MAX = 120.0
PERI_TARGET_AU = 0.3

ELEM = compute_patched_conic(r_p_AU=PERI_TARGET_AU)
T_HALF = ELEM.dt_flight_days


def _norm(v):
    return float(np.linalg.norm(v))


def _safe_lambert(r1, r2, tof_d, mu=GM_SUN, prograde=True, long_way=False):
    try:
        v1, v2, _ = solve_lambert_universal(
            r1, r2, day_to_sec(tof_d), mu,
            prograde=prograde, long_way=long_way)
        if np.any(np.isnan(v1)) or np.any(np.isnan(v2)):
            return None
        return v1, v2
    except Exception:
        return None


def main():
    print("=" * 66)
    print("M5 lunar return completion")
    print("=" * 66)
    print("  Pure lunar free return + lunar+return-DSM assessment")
    print()

    body_data = fetch_sem_vectors(use_cache=True)
    jd_arr = np.array(body_data["Earth"]["jd_tdb"], dtype=float)
    mjd_end = jd_arr[-1] - 2400000.5

    # [1] Run standard lunar trajectory
    print("[1] Running standard M5 lunar trajectory...")
    params = DesignParams(61066.0, R_MOON + 500.0, "trailing", 0.3 * AU_KM)
    traj = solve_trajectory(params, body_data, verbose=False)
    dep_vinf = traj.v_inf_earth
    t_end = 61066.0 + traj.t_total_days
    print(f"  t0=61066, t_end={t_end:.1f}, t_total={traj.t_total_days:.2f} d")
    print(f"  dep_vinf={dep_vinf:.4f} km/s")
    print(f"  r_p_achieved={km_to_au(traj.r_p_achieved_km):.4f} AU")

    # [2] Pure lunar free return check
    print("\n[2] Pure lunar free return check...")
    pure_check = compute_earth_return_vinf(
        traj.r_final, traj.v_final,
        traj.r_earth_final, traj.v_earth_final)
    print(f"  Valid Earth return: {pure_check['valid_return_event']}")
    print(f"  Distance to Earth: {pure_check['distance_to_earth_km']:.0f} km")

    # [3] Lunar + return DSM
    print("\n[3] Lunar + return DSM search...")
    r_peri = traj.r_final.copy()
    v_peri = traj.v_final.copy()
    r_sun_end, v_sun_end = interpolate_state_at_mjd(body_data, "Sun", t_end)
    r_moon_end, v_moon_end = interpolate_state_at_mjd(body_data, "Moon", t_end)
    gm4 = [GM_SUN, GM_EARTH, GM_MOON, 0.0]

    depart_offsets = [0, 5, 10, 15, 20, 30, 45, 60, 90]
    tof_return_list = [30, 45, 60, 75, 90, 120, 150, 180, 210, 240, 270, 300, 360]
    branches = [(True, False), (True, True)]

    # Propagate from perihelion forward
    r_ext = [r_sun_end.copy(), traj.r_earth_final.copy(),
             r_moon_end.copy(), r_peri.copy()]
    v_ext = [v_sun_end.copy(), traj.v_earth_final.copy(),
             v_moon_end.copy(), v_peri.copy()]
    states_at_offsets = {0: (r_peri.copy(), v_peri.copy())}
    max_offset = max(depart_offsets)
    for d in range(1, max_offset + 1):
        r_ext, v_ext = propagate_nbody(
            r_ext, v_ext, 86400.0, gm4, n_bodies=4, dt_internal=3600.0)
        cur_mjd = t_end + d
        try:
            r_e, v_e = interpolate_state_at_mjd(body_data, "Earth", cur_mjd)
            r_ext[1] = r_e.copy()
            v_ext[1] = v_e.copy()
        except Exception:
            pass
        if d in depart_offsets:
            states_at_offsets[d] = (r_ext[3].copy(), v_ext[3].copy())

    candidates = []
    evaluated = 0
    for d_off in depart_offsets:
        r_dep, v_dep = states_at_offsets[d_off]
        t_dep = t_end + d_off
        if t_dep > mjd_end - 30:
            continue
        for tof in tof_return_list:
            t_arr = t_dep + tof
            if t_arr > mjd_end:
                continue
            try:
                r_Earr, v_Earr = interpolate_state_at_mjd(body_data, "Earth", t_arr)
            except Exception:
                continue
            for pg, lw in branches:
                evaluated += 1
                leg = _safe_lambert(r_dep, r_Earr, tof, GM_SUN, pg, lw)
                if leg is None:
                    continue
                v_lam_dep, v_lam_arr = leg
                return_dsm = _norm(v_lam_dep - v_dep)
                if return_dsm > DSM_MAX:
                    continue
                r_sun_arr, v_sun_arr = interpolate_state_at_mjd(body_data, "Sun", t_arr)
                v_sc_helio = v_lam_arr - v_sun_arr
                v_e_helio = v_Earr - v_sun_arr
                arrival_vinf = _norm(v_sc_helio - v_e_helio)

                _, _, rp_km, _, _ = orbital_elements_from_state(r_dep, v_lam_dep, GM_SUN)
                rp_au = km_to_au(rp_km)
                overall_peri = min(rp_au, float(km_to_au(traj.r_p_achieved_km)))
                peri_err = abs(overall_peri - PERI_TARGET_AU)
                ret_brake = max(0, arrival_vinf - V_RET_MAX)
                total_dv = dep_vinf + 0.0 + return_dsm + ret_brake

                fair = bool(peri_err <= 0.03 and arrival_vinf <= V_RET_MAX and dep_vinf <= 20.0)
                near = bool(peri_err <= 0.05 and arrival_vinf <= 20.0 and dep_vinf <= 20.0)

                candidates.append({
                    "depart_offset_days": d_off,
                    "tof_return_days": float(tof),
                    "t_depart_mjd": float(t_dep),
                    "t_arrival_mjd": float(t_arr),
                    "return_dsm_kms": round(float(return_dsm), 4),
                    "arrival_return_vinf_kms": round(float(arrival_vinf), 4),
                    "arrival_braking_proxy_kms": round(float(ret_brake), 4),
                    "perihelion_AU": round(float(overall_peri), 6),
                    "peri_err_AU": round(float(peri_err), 6),
                    "total_dv_proxy_kms": round(float(total_dv), 4),
                    "fair": bool(fair),
                    "near_feasible": bool(near),
                })

    candidates.sort(key=lambda c: c["total_dv_proxy_kms"])
    fair = [c for c in candidates if c["fair"]]
    print(f"  Evaluated: {evaluated}, candidates: {len(candidates)}, fair: {len(fair)}")

    if fair:
        b = fair[0]
        print(f"  Best fair: offset={b['depart_offset_days']}d, "
              f"return_dsm={b['return_dsm_kms']:.2f}, "
              f"arrival_vinf={b['arrival_return_vinf_kms']:.2f}, "
              f"total={b['total_dv_proxy_kms']:.2f}")

    # Comparison with DSM no-lunar at t0=61066
    dsm_path = _REPO / "data" / "results" / "m5_dsm_no_lunar_search.json"
    comparison = None
    if dsm_path.exists() and fair:
        with open(dsm_path, "r", encoding="utf-8") as f:
            dsm_data = json.load(f)
        dsm_cands = [c for c in dsm_data.get("all_candidates", [])
                     if c.get("fair") and abs(c.get("t0_mjd", 0) - 61066.0) < 1]
        if dsm_cands:
            dsm_best = min(dsm_cands, key=lambda c: c["total_dv_proxy_kms"])
            dv_lu = fair[0]["total_dv_proxy_kms"]
            dv_dsm = dsm_best["total_dv_proxy_kms"]
            ratio = (dv_dsm - dv_lu) / dv_dsm if dv_dsm > 0 else None
            comparison = {
                "lunar_completed_total_kms": dv_lu,
                "no_lunar_dsm_total_kms": dv_dsm,
                "reference_saving_ratio": round(ratio, 6) if ratio else None,
                "mission_class": "lunar_plus_return_dsm_vs_no_lunar_dsm",
                "not_equivalent_to_pure_lunar_saving": True,
            }
            print(f"  Comparison with DSM no-lunar: lunar_completed={dv_lu:.2f}, "
                  f"DSM={dv_dsm:.2f}, ratio={ratio:.4f}")

    out = {
        "task": "M5 lunar return completion",
        "pure_lunar_free_return": {
            "valid_earth_return_found": pure_check["valid_return_event"],
            "distance_to_earth_km": pure_check["distance_to_earth_km"],
            "formal_return_vinf_kms": None,
            "formal_saving_ratio": None,
            "status": "return_event_missing",
            "classification": "FINITE_SEARCH_NEG",
        },
        "lunar_plus_return_dsm": {
            "num_candidates": len(candidates),
            "num_fair": len(fair),
            "best_fair": fair[0] if fair else None,
            "status": "completed" if fair else "no_candidate",
            "classification": "ACTUAL_RESULT (powered return, separate mission class)",
        },
        "comparison_with_no_lunar_dsm": comparison,
        "reference_ratio_classification": "DIAGNOSTIC",
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    jp = out_dir / "m5_lunar_return_completion.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
