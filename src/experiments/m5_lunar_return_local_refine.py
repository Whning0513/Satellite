"""
m5_lunar_return_local_refine.py
==================================
Local refinement around best near-miss for M5 lunar Earth return.

Best near miss from complete search:
  t0 = 61041.0, side = trailing, r_m = 2237.4 km
  closest Earth distance = 2,107,465 km

Goal: search finer grid around this point to see if a valid Earth return
(distance <= 1.5e6 km) can be found.
"""

import json, os, sys, time, math
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import GM_SUN, GM_EARTH, GM_MOON, AU_KM, R_MOON, DT_MAIN
from units import km_to_au
from trajectory import DesignParams, solve_trajectory, interpolate_state_at_mjd
from nbody import propagate_nbody
from event_semantics import compute_earth_return_vinf, classify_event
from horizons import fetch_sem_vectors
from mission_constraints import MISSION_LAUNCH_START_MJD, MISSION_LAUNCH_END_MJD

V_RET_MAX = 15.0
PERI_TARGET_AU = 0.3
PERI_TOL = 0.03
EARTH_THRESHOLD_KM = 1.5e6


def _norm(v):
    return float(np.linalg.norm(v))


def propagate_to_earth_return(r, v, t_start, bd, gm, max_days=500, thresh=EARTH_THRESHOLD_KM):
    """Continue N-body propagation to detect Earth return."""
    r = [ri.copy() for ri in r]
    v = [vi.copy() for vi in v]
    best_dist = 1e12
    best_day = -1; best_mjd = t_start
    best_sc = None; best_vsc = None; best_re = None; best_ve = None
    min_sun = 1e12

    for day in range(1, max_days + 1):
        r, v = propagate_nbody(r, v, 86400.0, gm, 4, dt_internal=3600.0)
        cur_mjd = t_start + day
        try:
            re, ve = interpolate_state_at_mjd(bd, "Earth", cur_mjd)
            r[1] = re.copy(); v[1] = ve.copy()
            rm_, vm_ = interpolate_state_at_mjd(bd, "Moon", cur_mjd)
            r[2] = rm_.copy(); v[2] = vm_.copy()
        except: pass
        sc = r[3]; d = _norm(sc - r[1])
        ds = _norm(sc - r[0])
        if ds < min_sun: min_sun = ds
        if d < best_dist:
            best_dist = d; best_day = day; best_mjd = cur_mjd
            best_sc = sc.copy(); best_vsc = v[3].copy()
            best_re = r[1].copy(); best_ve = v[1].copy()
        if best_dist < thresh and d > best_dist * 2: break

    if best_dist <= thresh:
        ec = compute_earth_return_vinf(best_sc, best_vsc, best_re, best_ve)
        rv = ec["return_vinf_kms"]
    else:
        rv = None

    return {"valid": bool(best_dist <= thresh), "dist_km": round(best_dist, 0),
            "day": best_day, "mjd": round(best_mjd, 2), "return_vinf": rv,
            "min_sun_AU": round(km_to_au(min_sun), 6)}


def main():
    print("=" * 66)
    print("M5 lunar return local refine")
    print("=" * 66)
    print("  Target: reduce closest approach from 2.107M km to <= 1.5M km")
    print()

    bd = fetch_sem_vectors(use_cache=True)
    jd_arr = np.array(bd["Earth"]["jd_tdb"], dtype=float)
    mjd_end = jd_arr[-1] - 2400000.5

    # Restrict to the formal 2026 launch window from the assignment.
    t0_list = list(range(int(MISSION_LAUNCH_START_MJD), min(int(MISSION_LAUNCH_END_MJD), 61052) + 1, 3))
    r_m_list = [R_MOON + 100, R_MOON + 500, R_MOON + 1000,
                R_MOON + 2000, R_MOON + 3000, R_MOON + 5000, R_MOON + 8000]
    side_list = ["trailing", "leading"]

    total = len(t0_list) * len(r_m_list) * len(side_list)
    print(f"  t0: {len(t0_list)} values ({t0_list[0]}–{t0_list[-1]})")
    print(f"  r_m: {len(r_m_list)} values")
    print(f"  sides: 2")
    print(f"  Total: {total}")
    print()

    t_start = time.time()
    results = []
    completed = 0

    for t0 in t0_list:
        for side in side_list:
            for rm in r_m_list:
                try:
                    params = DesignParams(float(t0), rm, side, PERI_TARGET_AU * AU_KM)
                    traj = solve_trajectory(params, bd, verbose=False, dt_integrate=DT_MAIN)
                    if not traj.success: continue
                except Exception:
                    continue

                t_end = float(t0) + traj.t_total_days
                rs, vs = interpolate_state_at_mjd(bd, "Sun", t_end)
                rm_, vm_ = interpolate_state_at_mjd(bd, "Moon", t_end)
                r = [rs.copy(), traj.r_earth_final.copy(), rm_.copy(), traj.r_final.copy()]
                v = [vs.copy(), traj.v_earth_final.copy(), vm_.copy(), traj.v_final.copy()]
                gm = [GM_SUN, GM_EARTH, GM_MOON, 0.0]

                ret = propagate_to_earth_return(r, v, t_end, bd, gm, max_days=500)
                peri_au = km_to_au(traj.r_p_achieved_km)
                peri_err = abs(peri_au - PERI_TARGET_AU)

                results.append({"t0_mjd": float(t0), "side": side,
                                "r_m_km": round(rm, 1),
                                "dep_vinf_kms": round(float(traj.v_inf_earth), 4),
                                "perihelion_AU": round(peri_au, 6),
                                "peri_err_AU": round(peri_err, 6),
                                "valid_earth_return": ret["valid"],
                                "closest_earth_km": ret["dist_km"],
                                "closest_mjd": ret["mjd"],
                                "return_vinf_kms": ret["return_vinf"],
                                "total_dv_proxy_kms": (
                                    round(traj.v_inf_earth + max(0, ret["return_vinf"] - V_RET_MAX), 4)
                                    if ret["valid"] and ret["return_vinf"] is not None else None),
                                "fair": bool(ret["valid"] and peri_err <= PERI_TOL)})
                completed += 1
                if completed % 20 == 0:
                    print(f"  Progress: {completed}/{total} ({time.time()-t_start:.0f}s)")

    t_elap = time.time() - t_start
    valid = [r for r in results if r["valid_earth_return"]]
    fair = [r for r in valid if r["fair"]]

    print(f"\n  Candidates: {len(results)}")
    print(f"  Earth return: {len(valid)}")
    print(f"  Fair complete: {len(fair)}")

    if fair:
        best = min(fair, key=lambda r: r["total_dv_proxy_kms"])
        print(f"\n  BEST VALID: t0={best['t0_mjd']:.0f} side={best['side']} "
              f"r_m={best['r_m_km']:.0f} km")
        print(f"    dist={best['closest_earth_km']:.0f} km "
              f"vinf={best['return_vinf_kms']:.2f} "
              f"total={best['total_dv_proxy_kms']:.2f}")
    elif valid:
        best_miss = min(valid, key=lambda r: r["closest_earth_km"])
        print(f"\n  BEST NEAR MISS: t0={best_miss['t0_mjd']:.0f} "
              f"side={best_miss['side']} r_m={best_miss['r_m_km']:.0f} km")
        print(f"    dist={best_miss['closest_earth_km']:.0f} km "
              f"peri={best_miss['perihelion_AU']:.4f} AU")

    out = {"task": "M5 lunar return local refine",
           "classification": "ACTUAL_RESULT" if fair else "FINITE_SEARCH_DIAGNOSTIC",
           "search_center": {"t0_near": 61041, "side": "trailing",
                             "r_m_near": 2237.4, "best_dist_km": 2107465},
           "search_space": {"t0_range": [t0_list[0], t0_list[-1]],
                            "t0_step_days": 3,
                            "r_m_range_km": [r_m_list[0], r_m_list[-1]],
                            "r_m_count": len(r_m_list),
                            "sides": side_list,
                            "max_return_days": 500},
           "num_candidates": len(results),
           "num_earth_return": len(valid),
           "num_fair_complete": len(fair),
           "best_valid": min(fair, key=lambda r: r["total_dv_proxy_kms"]) if fair else None,
           "best_near_miss": (min(valid, key=lambda r: r["closest_earth_km"])
                              if valid else min(results, key=lambda r: r["closest_earth_km"])
                              if results else None),
           "status": ("valid_found" if fair else
                      "near_miss_improved" if valid else "finite_search_negative"),
           }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    jp = out_dir / "m5_lunar_return_local_refine.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")

    import csv
    cp = out_dir / "m5_lunar_return_local_refine.csv"
    with open(cp, "w", newline="", encoding="utf-8") as f:
        if results:
            w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            w.writeheader(); w.writerows(results)
    print(f"Saved: {cp}")
    print(f"  Runtime: {t_elap:.0f}s")
    print("=" * 66)


if __name__ == "__main__":
    main()
