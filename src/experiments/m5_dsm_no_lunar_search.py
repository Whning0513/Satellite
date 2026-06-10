"""
m5_dsm_no_lunar_search.py
=========================
True M5 no-lunar DSM baseline search.

Earth(t0) -> DSM(r_dsm, theta_dsm, t_dsm) -> Earth(t_return)
Angular offset between Earth and DSM: 60-120 deg for Lambert convergence.
"""

import json, os, sys, time, math, itertools
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import GM_SUN, AU_KM
from units import km_to_au, au_to_km, day_to_sec
from lambert import solve_lambert_universal, orbital_elements_from_state
from trajectory import interpolate_state_at_mjd
from horizons import fetch_sem_vectors

V_RET_MAX = 15.0
V_DEP_MAX = 20.0
PERI_TARGET = 0.3


def _leg(r1, r2, tof_d, mu=GM_SUN, pg=True, lw=False):
    try:
        v1, v2, d = solve_lambert_universal(
            r1, r2, day_to_sec(tof_d), mu, prograde=pg, long_way=lw)
        if np.any(np.isnan(v1)): return None
        return v1, v2
    except Exception:
        return None


def main():
    print("=" * 66)
    print("M5 DSM no-lunar baseline search (real)")
    print("=" * 66)

    body_data = fetch_sem_vectors(use_cache=True)
    jd_arr = np.array(body_data["Earth"]["jd_tdb"], dtype=float)
    mjd_end = jd_arr[-1] - 2400000.5

    # Grid with known-working DSM geometry
    t0s = [61041.0, 61051.0, 61066.0, 61100.0, 61125.0, 61154.0,
           61200.0, 61213.0, 61300.0, 61370.0]
    rau_list = [0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
    angular_offsets_deg = [60, 80, 100, 120]  # Earth->DSM angular separation
    dt2_list = [60, 90, 120, 150, 180, 210, 240, 270, 300, 360]

    total_grid = len(t0s) * len(rau_list) * len(angular_offsets_deg) * len(dt2_list)
    print(f"  t0: {len(t0s)}, r: {len(rau_list)}, "
          f"offset: {len(angular_offsets_deg)}, dt2: {len(dt2_list)}")
    print(f"  Total combos: ~{total_grid}")
    print()

    t_start = time.time()
    candidates = []

    for t0 in t0s:
        try:
            rE0, vE0 = interpolate_state_at_mjd(body_data, "Earth", t0)
            theta0 = math.atan2(rE0[1], rE0[0])
        except Exception:
            continue

        for rau, off_deg, dt2 in itertools.product(
                rau_list, angular_offsets_deg, dt2_list):
            if dt2 < 30:
                continue

            theta_dsm = theta0 + math.radians(off_deg)
            rDSM = np.array([rau * AU_KM * math.cos(theta_dsm),
                             rau * AU_KM * math.sin(theta_dsm)])

            # Earth->DSM Lambert: find dt1 that works
            best_leg1 = None
            for dt1 in [30, 40, 50, 60, 70, 80, 90, 100, 120, 150]:
                leg1 = _leg(rE0, rDSM, dt1)
                if leg1 is None:
                    continue
                v1d, v1a = leg1
                dep_vinf = np.linalg.norm(v1d - vE0)
                if dep_vinf > V_DEP_MAX:
                    continue
                # Check perihelion
                a, e, rp, eps, h = orbital_elements_from_state(rE0, v1d, GM_SUN)
                peri = rp / AU_KM
                if peri < 0.2 or peri > 0.8:
                    continue  # too far from target
                if best_leg1 is None or dep_vinf < best_leg1["dv"]:
                    best_leg1 = {"dt1": dt1, "v1d": v1d, "v1a": v1a,
                                 "dv": dep_vinf, "peri": peri}
            if best_leg1 is None:
                continue

            t_dsm = t0 + best_leg1["dt1"]
            t_ret = t_dsm + dt2
            if t_ret > mjd_end:
                continue
            try:
                rEf, vEf = interpolate_state_at_mjd(body_data, "Earth", t_ret)
            except Exception:
                continue

            # DSM->Earth Lambert
            leg2 = _leg(rDSM, rEf, dt2)
            if leg2 is None:
                continue
            v2d, v2a = leg2
            ret_vinf = np.linalg.norm(v2a - vEf)

            # DSM impulse
            dsm_dv = np.linalg.norm(v2d - best_leg1["v1a"])
            dep_vinf = best_leg1["dv"]
            peri_err = abs(best_leg1["peri"] - PERI_TARGET)

            ret_brake = max(0, ret_vinf - V_RET_MAX)
            total_dv = dep_vinf + dsm_dv + ret_brake

            fair = bool(peri_err <= 0.03 and ret_vinf <= V_RET_MAX)
            near = bool(peri_err <= 0.05 and ret_vinf <= 20)

            candidates.append({
                "t0_mjd": float(t0),
                "dsm_mjd": float(t_dsm),
                "return_mjd": float(t_ret),
                "r_dsm_AU": float(rau),
                "dep_vinf_kms": round(float(dep_vinf), 4),
                "dsm_dv_kms": round(float(dsm_dv), 4),
                "ret_vinf_kms": round(float(ret_vinf), 4),
                "perihelion_AU": round(float(best_leg1["peri"]), 6),
                "peri_err_AU": round(float(peri_err), 6),
                "launch_proxy_kms": round(float(dep_vinf), 4),
                "ret_brake_proxy_kms": round(float(ret_brake), 4),
                "total_dv_proxy_kms": round(float(total_dv), 4),
                "fair": fair, "near_feasible": near,
            })

    t_elapsed = time.time() - t_start
    cand = sorted(candidates, key=lambda c: c["total_dv_proxy_kms"])
    fair = [c for c in cand if c["fair"]]
    near = [c for c in cand if c["near_feasible"]]

    print(f"  DSM candidates: {len(cand)} in {t_elapsed:.0f}s")
    print(f"  Strict fair: {len(fair)}")
    print(f"  Near-feasible: {len(near)}")
    if cand:
        b = cand[0]
        print(f"\n  Best:")
        print(f"    t0={b['t0_mjd']:.0f} dsm={b['dsm_mjd']:.0f} ret={b['return_mjd']:.0f}")
        print(f"    dep={b['dep_vinf_kms']:.2f} dsm={b['dsm_dv_kms']:.2f} "
              f"ret_vinf={b['ret_vinf_kms']:.2f}")
        print(f"    peri={b['perihelion_AU']:.4f} tot={b['total_dv_proxy_kms']:.2f}")
        print(f"    fair={b['fair']} near={b['near_feasible']}")
    if near:
        bn = min(near, key=lambda c: c["total_dv_proxy_kms"])
        print(f"\n  Best near-feasible:")
        print(f"    t0={bn['t0_mjd']:.0f} peri={bn['perihelion_AU']:.4f} "
              f"tot={bn['total_dv_proxy_kms']:.2f}")

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    summary = {
        "task": "M5 DSM no-lunar baseline search",
        "num_candidates": len(cand),
        "num_fair": len(fair),
        "num_near_feasible": len(near),
        "best_candidate": cand[0] if cand else None,
        "best_near_feasible": min(near, key=lambda c: c["total_dv_proxy_kms"]) if near else None,
        "status": ("fair_baseline_found" if fair else
                   "near_feasible_found" if near else "no_usable_baseline"),
    }
    jp = out_dir / "m5_dsm_no_lunar_search.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
