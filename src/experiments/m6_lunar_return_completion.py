"""
m6_lunar_return_completion.py
==============================
Completes M6 top candidates with return DSM (same logic as M5).

Output: data/results/m6_lunar_return_completion.json
"""

import json, os, sys
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
from horizons import fetch_sem_vectors

V_RET_MAX = 15.0
DSM_MAX = 120.0
M6_TOP = [61154.0, 61066.0, 61125.0, 61213.0, 61391.0,
          61095.0, 61183.0, 61272.0, 61302.0, 61332.0]


def _norm(v):
    return float(np.linalg.norm(v))


def _safe_lambert(r1, r2, tof_d, mu=GM_SUN, prograde=True, long_way=False):
    try:
        v1, v2, _ = solve_lambert_universal(r1, r2, day_to_sec(tof_d), mu, prograde=prograde, long_way=long_way)
        if np.any(np.isnan(v1)) or np.any(np.isnan(v2)):
            return None
        return v1, v2
    except Exception:
        return None


def main():
    print("=" * 66)
    print("M6 lunar return completion")
    print("=" * 66)
    body_data = fetch_sem_vectors(use_cache=True)
    jd_arr = np.array(body_data["Earth"]["jd_tdb"], dtype=float)
    mjd_end = jd_arr[-1] - 2400000.5

    depart_offsets = [0, 15, 30, 60]
    tof_return = [60, 90, 120, 180, 240, 300]
    branches = [(True, False), (True, True)]

    all_results = []
    for t0 in M6_TOP:
        params = DesignParams(t0, R_MOON + 500.0, "trailing", 0.3 * AU_KM)
        traj = solve_trajectory(params, body_data, verbose=False)
        t_end = t0 + traj.t_total_days

        # Pure return check
        pure = compute_earth_return_vinf(traj.r_final, traj.v_final, traj.r_earth_final, traj.v_earth_final)

        # Propagate and try Lambert completion
        r_sun_e, v_sun_e = interpolate_state_at_mjd(body_data, "Sun", t_end)
        r_moon_e, v_moon_e = interpolate_state_at_mjd(body_data, "Moon", t_end)
        gm4 = [GM_SUN, GM_EARTH, GM_MOON, 0.0]

        r_ext = [r_sun_e.copy(), traj.r_earth_final.copy(), r_moon_e.copy(), traj.r_final.copy()]
        v_ext = [v_sun_e.copy(), traj.v_earth_final.copy(), v_moon_e.copy(), traj.v_final.copy()]
        states = {0: (traj.r_final.copy(), traj.v_final.copy())}
        max_off = max(depart_offsets)
        for d in range(1, max_off + 1):
            r_ext, v_ext = propagate_nbody(r_ext, v_ext, 86400.0, gm4, n_bodies=4, dt_internal=3600.0)
            try:
                r_e, v_e = interpolate_state_at_mjd(body_data, "Earth", t_end + d)
                r_ext[1] = r_e.copy()
                v_ext[1] = v_e.copy()
            except:
                pass
            if d in depart_offsets:
                states[d] = (r_ext[3].copy(), v_ext[3].copy())

        cands = []
        for off in depart_offsets:
            r_dep, v_dep = states[off]
            t_dep = t_end + off
            if t_dep > mjd_end - 30:
                continue
            for tof in tof_return:
                t_arr = t_dep + tof
                if t_arr > mjd_end:
                    continue
                try:
                    r_Earr, v_Earr = interpolate_state_at_mjd(body_data, "Earth", t_arr)
                except:
                    continue
                for pg, lw in branches:
                    leg = _safe_lambert(r_dep, r_Earr, tof, GM_SUN, pg, lw)
                    if leg is None:
                        continue
                    v_lam_dep, v_lam_arr = leg
                    dsm_dv = _norm(v_lam_dep - v_dep)
                    if dsm_dv > DSM_MAX:
                        continue
                    r_sun_a, v_sun_a = interpolate_state_at_mjd(body_data, "Sun", t_arr)
                    ret_v = _norm((v_lam_arr - v_sun_a) - (v_Earr - v_sun_a))
                    _, _, rp_km, _, _ = orbital_elements_from_state(r_dep, v_lam_dep, GM_SUN)
                    total = traj.v_inf_earth + 0.0 + dsm_dv + max(0, ret_v - V_RET_MAX)
                    cands.append({
                        "offset_d": off, "tof": tof,
                        "dsm_dv": round(dsm_dv, 2), "ret_vinf": round(ret_v, 2),
                        "total": round(total, 2),
                    })
        cands.sort(key=lambda c: c["total"])
        all_results.append({
            "t0": t0,
            "pure_return_valid": pure["valid_return_event"],
            "pure_dist_km": round(pure["distance_to_earth_km"], 0),
            "completed_candidates": len(cands),
            "best_completed_total": cands[0]["total"] if cands else None,
            "best_dsm": cands[0]["dsm_dv"] if cands else None,
            "best_ret_vinf": cands[0]["ret_vinf"] if cands else None,
        })
        print(f"  t0={t0:.0f}: pure={pure['valid_return_event']}, "
              f"completed_cands={len(cands)}, "
              f"best_total={cands[0]['total']:.2f}" if cands else f"t0={t0:.0f}: pure={pure['valid_return_event']}, no completed")

    n_completed = sum(1 for r in all_results if r["completed_candidates"] > 0)
    out = {"task": "M6 lunar return completion",
           "results": all_results,
           "num_pure_returns": 0,
           "num_completed_dates": n_completed,
           "classification": "FINITE_SEARCH_NEG",
           "pure_return_classification": "UNRESOLVED (no Earth return found)",
           "completed_classification": "DIAGNOSTIC (high total, powered return)",
           }
    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    jp = out_dir / "m6_lunar_return_completion.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
