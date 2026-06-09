"""
m5_fair_saving_ratio_search.py
===============================
M5 fair saving ratio repair search.

Searches for a fair no-lunar baseline using:
A) Direct Earth-to-Earth Lambert transfer
B) Two-impulse DSM (deep-space maneuver) baseline

If found, computes saving_ratio = (no-lunar_total - lunar_total) / no-lunar_total.
Does NOT replace main M5 result without manual review.
"""

import json, os, sys, time, math, itertools
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import GM_SUN, GM_EARTH, AU_KM
from units import km_to_au, au_to_km, day_to_sec, sec_to_day
from lambert import solve_lambert_universal, orbital_elements_from_state
from trajectory import interpolate_state_at_mjd
from horizons import fetch_sem_vectors
from patched_conic import compute_patched_conic

V_RETURN_MAX = 15.0
V_DEPART_MAX = 20.0
PERI_TARGET = 0.3
PERI_TOL = 0.03  # ±0.03 AU = 10%


def solve_leg(r1, r2, tof_days, mu=GM_SUN, prograde=True, long_way=False):
    tof_s = day_to_sec(tof_days)
    try:
        v1, v2, diag = solve_lambert_universal(
            r1, r2, tof_s, mu, prograde=prograde, long_way=long_way)
        if np.any(np.isnan(v1)) or np.any(np.isnan(v2)):
            return None
        return v1, v2
    except Exception:
        return None


def evaluate_direct(t0, tof, branch, body_data):
    """Evaluate a direct Earth-to-Earth Lambert transfer."""
    try:
        rE0, vE0 = interpolate_state_at_mjd(body_data, "Earth", t0)
        rE1, vE1 = interpolate_state_at_mjd(body_data, "Earth", t0 + tof)
    except Exception:
        return None
    leg = solve_leg(rE0, rE1, tof, GM_SUN, prograde=branch[0], long_way=branch[1])
    if leg is None:
        return None
    v1, v2 = leg
    dep_vinf = np.linalg.norm(v1 - vE0)
    ret_vinf = np.linalg.norm(v2 - vE1)
    a, e, rp, eps, h = orbital_elements_from_state(rE0, v1, GM_SUN)
    peri = rp / AU_KM
    peri_err = abs(peri - PERI_TARGET)
    return {
        "t0_mjd": float(t0), "return_mjd": float(t0 + tof), "tof_days": float(tof),
        "dep_vinf_kms": float(round(dep_vinf, 4)),
        "ret_vinf_kms": float(round(ret_vinf, 4)),
        "perihelion_AU": float(round(peri, 6)),
        "peri_err_AU": float(round(peri_err, 6)),
        "fair": bool(peri_err <= PERI_TOL and ret_vinf <= V_RETURN_MAX and dep_vinf <= V_DEPART_MAX),
    }


def evaluate_dsm(t0, tof1, tof2, f_dsm, body_data):
    """Evaluate a two-impulse DSM baseline.

    Earth departure -> coast to DSM point -> impulse -> coast to Earth return.
    f_dsm: fraction of total TOF for first leg.
    """
    tof = tof1 + tof2
    try:
        rE0, vE0 = interpolate_state_at_mjd(body_data, "Earth", t0)
        rE1, vE1 = interpolate_state_at_mjd(body_data, "Earth", t0 + tof)
    except Exception:
        return None
    # DSM point: coast position along Earth's orbit
    # Simple approximation: linear scaling of Earth position
    t_dsm = t0 + tof1
    try:
        rDSM, vDSM = interpolate_state_at_mjd(body_data, "Earth", t_dsm)
    except Exception:
        return None
    # Lambert: Earth->DSM
    leg1 = solve_leg(rE0, rDSM, tof1, GM_SUN, prograde=True, long_way=False)
    if leg1 is None:
        return None
    v1_dep, v1_arr = leg1
    # Lambert: DSM->Earth
    leg2 = solve_leg(rDSM, rE1, tof2, GM_SUN, prograde=True, long_way=False)
    if leg2 is None:
        return None
    v2_dep, v2_arr = leg2
    # DSM impulse
    dsm_dv = np.linalg.norm(v2_dep - v1_arr)

    dep_vinf = np.linalg.norm(v1_dep - vE0)
    ret_vinf = np.linalg.norm(v2_arr - vE1)
    a, e, rp, eps, h = orbital_elements_from_state(rE0, v1_dep, GM_SUN)
    peri = rp / AU_KM
    peri_err = abs(peri - PERI_TARGET)

    total_dv = dep_vinf + dsm_dv + max(0, ret_vinf - V_RETURN_MAX)

    return {
        "t0_mjd": float(t0), "tof1_days": float(tof1), "tof2_days": float(tof2),
        "dep_vinf_kms": float(round(dep_vinf, 4)),
        "dsm_dv_kms": float(round(dsm_dv, 4)),
        "ret_vinf_kms": float(round(ret_vinf, 4)),
        "total_dv_kms": float(round(total_dv, 4)),
        "perihelion_AU": float(round(peri, 6)),
        "peri_err_AU": float(round(peri_err, 6)),
        "fair": bool(peri_err <= PERI_TOL and ret_vinf <= V_RETURN_MAX and dep_vinf <= V_DEPART_MAX),
    }


def main():
    print("=" * 66)
    print("M5 fair saving ratio search")
    print("=" * 66)
    body_data = fetch_sem_vectors(use_cache=True)
    jd_arr = np.array(body_data["Earth"]["jd_tdb"], dtype=float)
    mjd_end = jd_arr[-1] - 2400000.5

    # --- Lunar candidate (M5 nominal) ---
    lunar = {
        "t0_mjd": 61066.0,
        "dep_vinf_kms": 10.12,  # from M5 v_inf_earth
        "ret_vinf_kms": 77.88,  # v_rel_earth
        "perihelion_AU": 0.2843,
        "note": "M5 nominal lunar candidate"
    }

    # --- A: Direct Lambert search ---
    print("\n[A] Direct Earth-to-Earth Lambert search...")
    t0_grid = list(range(61041, int(min(mjd_end, 61500)), 20))
    tof_grid = list(range(180, 730, 20))
    branches = [(True, False), (True, True)]

    direct_candidates = []
    for t0, tof, b in itertools.product(t0_grid, tof_grid, branches):
        c = evaluate_direct(t0, tof, b, body_data)
        if c:
            direct_candidates.append(c)
    fair_direct = [c for c in direct_candidates if c["fair"]]
    print(f"  Direct candidates: {len(direct_candidates)}, fair: {len(fair_direct)}")
    if fair_direct:
        best_direct = min(fair_direct, key=lambda c: c["peri_err_AU"])
        print(f"  Best direct: t0={best_direct['t0_mjd']:.0f} peri={best_direct['perihelion_AU']:.4f} "
              f"ret_vinf={best_direct['ret_vinf_kms']:.1f}")

    # --- B: DSM search ---
    print("\n[B] DSM no-lunar search...")
    dsm_candidates = []
    for t0 in t0_grid[:10]:
        for tof1 in [30, 60, 90, 120]:
            for tof2 in [60, 90, 120, 180]:
                c = evaluate_dsm(t0, tof1, tof2, 0.5, body_data)
                if c:
                    dsm_candidates.append(c)
    fair_dsm = [c for c in dsm_candidates if c["fair"]]
    print(f"  DSM candidates: {len(dsm_candidates)}, fair: {len(fair_dsm)}")
    if fair_dsm:
        best_dsm = min(fair_dsm, key=lambda c: c["total_dv_kms"])
        print(f"  Best DSM: t0={best_dsm['t0_mjd']:.0f} total_dv={best_dsm['total_dv_kms']:.1f} "
              f"peri={best_dsm['perihelion_AU']:.4f} ret_vinf={best_dsm['ret_vinf_kms']:.1f}")

    # --- Saving ratio ---
    saving_ratio = None
    status = "no_fair_baseline_after_extended_search"
    best_nl_total = None

    if fair_direct:
        best_d = min(fair_direct, key=lambda c: abs(c["perihelion_AU"] - PERI_TARGET))
        nl_total = best_d["dep_vinf_kms"] + max(0, best_d["ret_vinf_kms"] - V_RETURN_MAX)
        best_nl_total = nl_total
        lunar_total = lunar["dep_vinf_kms"] + max(0, lunar["ret_vinf_kms"] - V_RETURN_MAX)
        saving_ratio = (nl_total - lunar_total) / nl_total if nl_total > 0 else 0
        status = "fair_ratio_found"
        print(f"\n  Direct baseline total_dv: {nl_total:.1f}")
        print(f"  Lunar total_dv: {lunar_total:.1f}")
        print(f"  Saving ratio: {saving_ratio:.2%}")
    elif fair_dsm:
        best_d = min(fair_dsm, key=lambda c: abs(c["perihelion_AU"] - PERI_TARGET))
        nl_total = best_d["total_dv_kms"]
        best_nl_total = nl_total
        lunar_total = lunar["dep_vinf_kms"] + max(0, lunar["ret_vinf_kms"] - V_RETURN_MAX)
        saving_ratio = (nl_total - lunar_total) / nl_total if nl_total > 0 else 0
        status = "dsm_saving_ratio_found"
        print(f"\n  DSM baseline total_dv: {nl_total:.1f}")
        print(f"  Lunar total_dv: {lunar_total:.1f}")
        print(f"  Saving ratio: {saving_ratio:.2%}")

    # --- Save ---
    out = {
        "task": "M5 fair saving ratio repair search",
        "direct_no_lunar": {
            "num_candidates": len(direct_candidates),
            "num_fair": len(fair_direct),
            "best_fair": fair_direct[0] if fair_direct else None,
        },
        "dsm_no_lunar": {
            "num_candidates": len(dsm_candidates),
            "num_fair": len(fair_dsm),
            "best_fair": fair_dsm[0] if fair_dsm else None,
        },
        "lunar_candidate": lunar,
        "saving_ratio": round(saving_ratio, 4) if saving_ratio is not None else None,
        "status": status,
        "conclusion": (
            "Fair no-lunar baseline found."
            if saving_ratio
            else ("No fair baseline. Direct %d/%d fair, DSM %d/%d fair."
                  % (len(fair_direct), len(direct_candidates),
                     len(fair_dsm), len(dsm_candidates)))
        ),
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    jp = out_dir / "m5_fair_saving_ratio_search.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")
    print(f"\n{'='*66}")
    print(f"M5 saving ratio search: {status}")
    print("="*66)


if __name__ == "__main__":
    main()
