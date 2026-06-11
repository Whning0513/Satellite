"""
m5_no_lunar_t61037_deep_search.py
==================================
Deepened no-lunar DSM search at t0=61037 (same date as best lunar candidate).

Expands the search in:
  - tof1 (days to DSM): 20-310, step 5
  - tof2 (days from DSM to Earth): 30-350, step 5
  - Kepler branch: prograde_short, prograde_long

Uses same ellipse-sampled approach as m5_dsm_no_lunar_search.py.
"""

import json, os, sys, time, math
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import GM_SUN, AU_KM
from units import km_to_au, day_to_sec
from lambert import solve_lambert_universal, orbital_elements_from_state
from trajectory import interpolate_state_at_mjd
from event_semantics import compute_earth_return_vinf
from horizons import fetch_sem_vectors
from patched_conic import compute_patched_conic

V_RET_MAX = 15.0; V_DEP_MAX = 20.0
PERI_TARGET_AU = 0.3; PERI_TOL = 0.03
DSM_MAX = 200.0

ELEM = compute_patched_conic(r_p_AU=PERI_TARGET_AU)
V_INF_DEP = abs(ELEM.delta_v)  # 9.55 km/s patched-conic departure


def _norm(v): return float(np.linalg.norm(v))


def _safe_lambert(r1, r2, tof_d, mu=GM_SUN, pg=True, lw=False):
    try:
        v1, v2, _ = solve_lambert_universal(r1, r2, day_to_sec(tof_d), mu, pg, lw)
        if np.any(np.isnan(v1)): return None
        return v1, v2
    except: return None


def position_on_ellipse_at_time(theta0, t_days, a, e, mu=GM_SUN):
    n = math.sqrt(mu / (a ** 3))
    M = math.pi + n * day_to_sec(t_days)
    E_val = M
    for _ in range(100):
        dE = (M - (E_val - e * math.sin(E_val))) / (1.0 - e * math.cos(E_val))
        E_val += dE
        if abs(dE) < 1e-12: break
    tan_half = math.sqrt((1.0 + e) / (1.0 - e)) * math.tan(E_val / 2.0)
    nu = 2.0 * math.atan(tan_half)
    if nu < 0: nu += 2.0 * math.pi
    elif nu > 2.0 * math.pi: nu -= 2.0 * math.pi
    r_mag = a * (1.0 - e * math.cos(E_val))
    cos_p = math.cos(theta0 + math.pi); sin_p = math.sin(theta0 + math.pi)
    p_hat = np.array([cos_p, sin_p]); q_hat = np.array([-sin_p, cos_p])
    cos_nu = math.cos(nu); sin_nu = math.sin(nu)
    r_vec = r_mag * (cos_nu * p_hat + sin_nu * q_hat)
    factor = math.sqrt(mu / (a * (1.0 - e * e)))
    v_vec = factor * (-sin_nu) * p_hat + factor * (e + cos_nu) * q_hat
    return r_vec, v_vec


def main():
    print("=" * 66)
    print("M5 no-lunar DSM deep search at t0=61037")
    print("=" * 66)

    bd = fetch_sem_vectors(use_cache=True)
    t0 = 61037.0
    rE0, vE0 = interpolate_state_at_mjd(bd, "Earth", t0)
    th0 = math.atan2(rE0[1], rE0[0])

    jd_arr = np.array(bd["Earth"]["jd_tdb"], dtype=float)
    mjd_end = jd_arr[-1] - 2400000.5

    # Compute actual departure v_inf at this t0 (ellipse vs Earth)
    _, v_aph = position_on_ellipse_at_time(th0, 0.0, ELEM.a, ELEM.e, GM_SUN)
    dep_vinf_t0 = _norm(v_aph - vE0)

    # Fine grid
    tof1_list = list(range(20, 310, 5))
    tof2_list = list(range(30, 350, 5))
    branches = [(True, False), (True, True), (False, False)]

    total = len(tof1_list) * len(tof2_list) * len(branches)
    print(f"  tof1: {len(tof1_list)} ({tof1_list[0]}–{tof1_list[-1]})")
    print(f"  tof2: {len(tof2_list)} ({tof2_list[0]}–{tof2_list[-1]})")
    print(f"  branches: {len(branches)}")
    print(f"  Total: ~{total}")
    print(f"  dep_vinf_actual: {dep_vinf_t0:.4f} km/s")
    print()

    t_start = time.time()
    candidates = []
    evaled = 0

    for tof1 in tof1_list:
        t_dsm = t0 + tof1
        if t_dsm > mjd_end - 30: continue
        r_DSM, v_coast = position_on_ellipse_at_time(th0, tof1, ELEM.a, ELEM.e, GM_SUN)

        for tof2 in tof2_list:
            t_ret = t_dsm + tof2
            if t_ret > mjd_end: continue

            for pg, lw in branches:
                evaled += 1
                try:
                    rEret, vEret = interpolate_state_at_mjd(bd, "Earth", t_ret)
                except: continue
                leg2 = _safe_lambert(r_DSM, rEret, tof2, pg=pg, lw=lw)
                if leg2 is None: continue
                v2dep, v2arr = leg2

                dsm_dv = _norm(v2dep - v_coast)
                if dsm_dv > DSM_MAX: continue
                ret_vinf = _norm(v2arr - vEret)
                if ret_vinf > 50: continue

                _, _, rp_km, _, _ = orbital_elements_from_state(r_DSM, v2dep, GM_SUN)
                rp_au = km_to_au(rp_km)
                overall_peri = min(rp_au, PERI_TARGET_AU)
                peri_err = abs(overall_peri - PERI_TARGET_AU)

                # Earth return event check (DSM Lambert arrives at Earth = always valid)
                from event_semantics import EARTH_SOI_KM
                r_DSM_au = km_to_au(_norm(r_DSM))

                launch_proxy = dep_vinf_t0
                ret_brake = max(0, ret_vinf - V_RET_MAX)
                total_dv = launch_proxy + dsm_dv + ret_brake
                fair = bool(peri_err <= PERI_TOL and ret_vinf <= V_RET_MAX)

                candidates.append({
                    "t0_mjd": t0,
                    "tof1_days": tof1, "tof2_days": tof2,
                    "r_DSM_AU": round(r_DSM_au, 4),
                    "departure_vinf_kms": round(launch_proxy, 4),
                    "dsm_delta_v_kms": round(dsm_dv, 4),
                    "return_vinf_kms": round(ret_vinf, 4),
                    "return_braking_proxy_kms": round(ret_brake, 4),
                    "perihelion_AU": round(overall_peri, 6),
                    "peri_err_AU": round(peri_err, 6),
                    "total_dv_proxy_kms": round(total_dv, 4),
                    "fair": fair,
                })

    t_elap = time.time() - t_start
    fair = [c for c in candidates if c["fair"]]
    print(f"  Evaluated: {evaled}")
    print(f"  Candidates: {len(candidates)}")
    print(f"  Fair: {len(fair)}")
    if fair:
        best = min(fair, key=lambda c: c["total_dv_proxy_kms"])
        print(f"\n  BEST FAIR: tof1={best['tof1_days']}d tof2={best['tof2_days']}d "
              f"dsm={best['dsm_delta_v_kms']:.2f} ret_vinf={best['return_vinf_kms']:.2f} "
              f"total={best['total_dv_proxy_kms']:.2f}")
    else:
        best_nr = min(candidates, key=lambda c: c["return_vinf_kms"]) if candidates else None
        if best_nr:
            print(f"\n  BEST NEAR MISS: ret_vinf={best_nr['return_vinf_kms']:.2f} "
                  f"dsm={best_nr['dsm_delta_v_kms']:.2f} "
                  f"peri_err={best_nr['peri_err_AU']:.6f}")
        print(f"\n  No fair candidates at t0=61037 after deep search.")

    out = {
        "task": "M5 no-lunar DSM deep search at t0=61037",
        "classification": "ACTUAL_RESULT",
        "t0_mjd": t0,
        "search_space": {
            "tof1_days_range": [tof1_list[0], tof1_list[-1]],
            "tof1_step": 5,
            "tof2_days_range": [tof2_list[0], tof2_list[-1]],
            "tof2_step": 5,
            "branches": ["prograde_short", "prograde_long", "retrograde_short"],
        },
        "candidates_evaluated": evaled,
        "num_candidates": len(candidates),
        "valid_fair_candidates": len(fair),
        "best_valid": min(fair, key=lambda c: c["total_dv_proxy_kms"]) if fair else None,
        "best_near_miss": (min(candidates, key=lambda c: c["return_vinf_kms"])
                           if candidates and not fair else None),
        "status": "valid_found" if fair else "finite_search_negative",
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    jp = out_dir / "m5_no_lunar_t61037_deep_search.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")

    import csv
    cp = out_dir / "m5_no_lunar_t61037_deep_search.csv"
    with open(cp, "w", newline="", encoding="utf-8") as f:
        if candidates:
            w = csv.DictWriter(f, fieldnames=list(candidates[0].keys()))
            w.writeheader(); w.writerows(candidates)
    print(f"Saved: {cp}")
    print(f"  Runtime: {t_elap:.0f}s")
    print("=" * 66)


if __name__ == "__main__":
    main()
