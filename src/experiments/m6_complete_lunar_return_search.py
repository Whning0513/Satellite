"""
m6_complete_lunar_return_search.py
====================================
Extends M6 top candidates to full-period propagation with Earth return detection.

Output: data/results/m6_complete_lunar_return_search.json
"""

import json, os, sys, time
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import GM_SUN, GM_EARTH, GM_MOON, AU_KM, R_MOON
from units import km_to_au
from trajectory import DesignParams, solve_trajectory, interpolate_state_at_mjd
from nbody import propagate_nbody
from event_semantics import compute_earth_return_vinf
from horizons import fetch_sem_vectors

EARTH_THRESHOLD_KM = 1.5e6
M6_DATES = [61154.0, 61066.0, 61125.0, 61213.0, 61391.0,
            61095.0, 61183.0, 61272.0, 61302.0, 61332.0]


def _norm(v):
    return float(np.linalg.norm(v))


def propagate_to_earth_return(r, v, t_start, bd, gm, max_days=600, thresh=EARTH_THRESHOLD_KM):
    """Same as M5 version — continue propagation to detect Earth return."""
    r = [ri.copy() for ri in r]
    v = [vi.copy() for vi in v]
    best_dist = np.inf
    best_day = -1
    best_mjd = t_start
    best_sc = None; best_vsc = None; best_re = None; best_ve = None
    min_sun = np.inf

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
        return_vinf = ec["return_vinf_kms"]
    else:
        return_vinf = None

    return {
        "valid_earth_return": bool(best_dist <= thresh),
        "closest_dist_km": round(best_dist, 0),
        "best_day": best_day,
        "return_vinf_kms": return_vinf,
        "min_sun_AU": round(km_to_au(min_sun), 6),
    }


def main():
    print("=" * 66)
    print("M6 complete lunar return search")
    print("=" * 66)
    bd = fetch_sem_vectors(use_cache=True)
    results = []

    for t0 in M6_DATES:
        try:
            params = DesignParams(t0, R_MOON+500, "trailing", 0.3*AU_KM)
            traj = solve_trajectory(params, bd, verbose=False)
        except: continue

        t_end = t0 + traj.t_total_days
        rs, vs = interpolate_state_at_mjd(bd, "Sun", t_end)
        rm, vm = interpolate_state_at_mjd(bd, "Moon", t_end)
        r = [rs.copy(), traj.r_earth_final.copy(), rm.copy(), traj.r_final.copy()]
        v = [vs.copy(), traj.v_earth_final.copy(), vm.copy(), traj.v_final.copy()]
        gm = [GM_SUN, GM_EARTH, GM_MOON, 0.0]

        ret = propagate_to_earth_return(r, v, t_end, bd, gm)
        results.append({"t0_mjd": t0, **ret})

    n_valid = sum(1 for r in results if r["valid_earth_return"])
    print(f"  Candidates: {len(results)}, valid Earth return: {n_valid}")
    if results:
        nearest = min(results, key=lambda r: r["closest_dist_km"])
        print(f"  Closest approach: t0={nearest['t0_mjd']:.0f} "
              f"dist={nearest['closest_dist_km']:.0f} km")

    out = {"task": "M6 complete lunar return search",
           "classification": "ACTUAL_RESULT",
           "num_candidates": len(results),
           "num_earth_return": n_valid,
           "results": results,
           "status": ("complete_found" if n_valid else "no_complete_lunar_return_found"),
           }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    jp = out_dir / "m6_complete_lunar_return_search.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
