"""
m5_fixed_date_no_lunar_for_lunar_best.py
=========================================
Search for no-lunar DSM baseline at t0=61037 (same date as best lunar candidate).

Two approaches:
  A. Direct Lambert Earth→Earth at t0=61037.
  B. DSM no-lunar (ellipse-sampled) at t0=61037.

Output: data/results/m5_fixed_date_no_lunar_t61037.json
"""

import json, os, sys, math
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import GM_SUN, AU_KM
from units import km_to_au, day_to_sec
from trajectory import interpolate_state_at_mjd
from lambert import solve_lambert_universal, orbital_elements_from_state
from event_semantics import compute_earth_return_vinf
from horizons import fetch_sem_vectors
from patched_conic import compute_patched_conic

V_RET_MAX = 15.0
PERI_TARGET_AU = 0.3
PERI_TOL = 0.03
T0 = 61037.0

ELEM = compute_patched_conic(r_p_AU=PERI_TARGET_AU)
V_INF_DEP = abs(ELEM.delta_v)  # ~9.55 km/s


def _norm(v):
    return float(np.linalg.norm(v))


def _safe_lambert(r1, r2, tof_d, mu=GM_SUN, pg=True, lw=False):
    try:
        v1, v2, _ = solve_lambert_universal(r1, r2, day_to_sec(tof_d), mu, pg, lw)
        if np.any(np.isnan(v1)): return None
        return v1, v2
    except: return None


def main():
    print("=" * 66)
    print("No-lunar baselines at t0=61037 (lunar best date)")
    print("=" * 66)

    bd = fetch_sem_vectors(use_cache=True)

    # ── A: Direct Lambert ──
    print("\n[A] Direct Earth→Earth Lambert...")
    rE0, vE0 = interpolate_state_at_mjd(bd, "Earth", T0)
    candidatos = []
    for tof in range(100, 731, 5):
        rE1, vE1 = interpolate_state_at_mjd(bd, "Earth", T0 + tof)
        for pg, lw in [(True, False), (True, True)]:
            leg = _safe_lambert(rE0, rE1, tof, pg=pg, lw=lw)
            if leg is None: continue
            v1, v2 = leg
            dep = _norm(v1 - vE0); ret = _norm(v2 - vE1)
            a, e, rp, *_ = orbital_elements_from_state(rE0, v1, GM_SUN)
            rp_au = km_to_au(rp)
            candidatos.append({"tof": tof, "pg": pg, "lw": lw,
                               "dep_vinf": round(dep, 4),
                               "ret_vinf": round(ret, 4),
                               "peri": round(rp_au, 6),
                               "fair": bool(abs(rp_au - PERI_TARGET_AU) <= PERI_TOL
                                            and ret <= V_RET_MAX and dep <= 20.0)})
    fair_dir = [c for c in candidatos if c["fair"]]
    print(f"  Direct candidates: {len(candidatos)}, fair: {len(fair_dir)}")

    # ── B: DSM ellipse-sampled ──
    print("\n[B] DSM no-lunar at t0=61037...")
    from experiments.m5_dsm_no_lunar_search import position_on_ellipse_at_time, ELEM
    th0 = math.atan2(rE0[1], rE0[0])
    dsm_cands = []
    for tof1 in range(20, 300, 15):
        rDSM, v_coast = position_on_ellipse_at_time(th0, tof1, ELEM.a, ELEM.e, GM_SUN)
        t_dsm = T0 + tof1
        for tof2 in range(30, 300, 15):
            t_ret = t_dsm + tof2
            try:
                rEret, vEret = interpolate_state_at_mjd(bd, "Earth", t_ret)
            except: continue
            for pg, lw in [(True, False), (True, True)]:
                leg = _safe_lambert(rDSM, rEret, tof2, pg=pg, lw=lw)
                if leg is None: continue
                v2dep, v2arr = leg
                dsm_dv = _norm(v2dep - v_coast); ret_vinf = _norm(v2arr - vEret)
                _, _, rp_km, *_ = orbital_elements_from_state(rDSM, v2dep, GM_SUN)
                rp_au = km_to_au(rp_km)
                total = V_INF_DEP + dsm_dv + max(0, ret_vinf - V_RET_MAX)
                fair = abs(rp_au - PERI_TARGET_AU) <= PERI_TOL and ret_vinf <= V_RET_MAX
                dsm_cands.append({"tof1": tof1, "tof2": tof2,
                                  "dsm_dv": round(dsm_dv, 4),
                                  "ret_vinf": round(ret_vinf, 4),
                                  "peri": round(rp_au, 6),
                                  "total": round(total, 4),
                                  "fair": fair})
    fair_dsm = [c for c in dsm_cands if c["fair"]]
    print(f"  DSM candidates: {len(dsm_cands)}, fair: {len(fair_dsm)}")

    # Best pick
    best_dsm = min(fair_dsm, key=lambda c: c["total"]) if fair_dsm else None
    best_dir = min(fair_dir, key=lambda c: c["ret_vinf"]) if fair_dir else None

    out = {
        "task": "No-lunar baselines at t0=61037",
        "t0_mjd": T0,
        "direct_lambert": {
            "num_candidates": len(candidatos),
            "num_fair": len(fair_dir),
            "best_fair": best_dir,
        },
        "dsm_no_lunar": {
            "num_candidates": len(dsm_cands),
            "num_fair": len(fair_dsm),
            "best_fair": best_dsm,
        },
        "no_lunar_dsm_valid": bool(fair_dsm),
        "no_lunar_direct_valid": bool(fair_dir),
        "best_no_lunar": best_dsm or best_dir,
        "same_date_comparison_possible": bool(fair_dsm or fair_dir),
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    jp = out_dir / "m5_fixed_date_no_lunar_t61037.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
