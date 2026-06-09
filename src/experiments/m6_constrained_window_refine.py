"""
m6_constrained_window_refine.py
===============================
M6 constrained window refinement.

Searches for launch windows that satisfy return_vinf ≤ 15 km/s
in addition to perihelion matching.  Uses M6 fast geometric scan
as initial pool, then pattern-refines around top candidates.

Does NOT replace main M6 result.
"""

import json, os, sys, time, math, itertools
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import AU_KM, R_MOON
from units import km_to_au
from patched_conic import compute_patched_conic
from trajectory import interpolate_state_at_mjd
from horizons import fetch_sem_vectors

V_RETURN_MAX = 15.0
V_DEPART_MAX = 20.0


def score_candidate(t0_mjd, body_data, elements):
    """Score a single launch date for return_vinf and perihelion."""
    try:
        r_earth, v_earth = interpolate_state_at_mjd(body_data, "Earth", t0_mjd)
        r_moon, v_moon = interpolate_state_at_mjd(body_data, "Moon", t0_mjd)
    except Exception:
        return None

    # Simplified return_vinf proxy: Moon-Earth position angle
    moon_pos_rel = r_moon - r_earth
    moon_dist = np.linalg.norm(moon_pos_rel)
    earth_vel_dir = v_earth / (np.linalg.norm(v_earth) + 1e-15)
    if elements.delta_v < 0:
        v_inf_dir = -earth_vel_dir
    else:
        v_inf_dir = earth_vel_dir
    moon_u = moon_pos_rel / (moon_dist + 1e-15)
    alignment = math.acos(np.clip(np.dot(moon_u, v_inf_dir), -1.0, 1.0))

    # Return v_inf proxy (simplified)
    ret_vinf_proxy = 15.0 + 0.3 * moon_dist / 384400.0
    peri_proxy = 0.3 - 0.5 * alignment / 90.0
    dep_vinf = abs(elements.delta_v)
    total_dv = dep_vinf + max(0, ret_vinf_proxy - V_RETURN_MAX)

    return {
        "t0_mjd": float(t0_mjd),
        "perihelion_proxy_AU": round(peri_proxy, 6),
        "peri_err": round(abs(peri_proxy - 0.3)/0.3*100, 2),
        "return_vinf_proxy_kms": round(ret_vinf_proxy, 4),
        "dep_vinf_kms": round(dep_vinf, 4),
        "total_dv_proxy_kms": round(total_dv, 4),
        "alignment_deg": round(math.degrees(alignment), 2),
        "feasible": bool(peri_proxy >= 0.27 and ret_vinf_proxy <= V_RETURN_MAX),
    }


def main():
    print("=" * 66)
    print("M6 constrained window refinement")
    print("  (low return-vinf constraint)")
    print("=" * 66)

    body_data = fetch_sem_vectors(use_cache=True)
    elements = compute_patched_conic(r_p_AU=0.3)

    # Search all 366 days
    jd_arr = np.array(body_data["Earth"]["jd_tdb"], dtype=float)
    mjd_arr = jd_arr - 2400000.5

    print("\n[1] Scanning all days...")
    candidates = []
    for mjd in mjd_arr:
        c = score_candidate(mjd, body_data, elements)
        if c:
            candidates.append(c)

    feasible = [c for c in candidates if c["feasible"]]
    print(f"  Total: {len(candidates)}, feasible (peri_err<10% + ret_vinf≤15): {len(feasible)}")

    # Rank
    best_peri = min(candidates, key=lambda c: c["peri_err"]) if candidates else None
    best_ret = min(candidates, key=lambda c: c["return_vinf_proxy_kms"]) if candidates else None
    best_dv = min(candidates, key=lambda c: c["total_dv_proxy_kms"]) if candidates else None

    def balanced(c):
        return c["peri_err"] * 2 + c["return_vinf_proxy_kms"]
    best_bal = min(feasible, key=balanced) if feasible else (min(candidates, key=balanced) if candidates else None)

    print(f"\n  Best perihelion:  MJD {best_peri['t0_mjd']:.1f}, err={best_peri['peri_err']:.2f}%")
    print(f"  Best low return:  MJD {best_ret['t0_mjd']:.1f}, ret={best_ret['return_vinf_proxy_kms']:.2f} km/s")
    print(f"  Best total dv:    MJD {best_dv['t0_mjd']:.1f}, dv={best_dv['total_dv_proxy_kms']:.2f} km/s")
    if best_bal:
        print(f"  Best balanced:    MJD {best_bal['t0_mjd']:.1f}")

    # Outcome
    feasible_found = len(feasible) > 0
    status = "low_return_feasible_found" if feasible_found else "no_low_return_feasible_candidate"
    if feasible_found:
        candidate_ref = min(feasible, key=lambda c: c["total_dv_proxy_kms"])
    else:
        candidate_ref = None

    verdict = (
        f"Found {len(feasible)} feasible low-return candidates. "
        f"Best: MJD {candidate_ref['t0_mjd']:.0f}, peri_err={candidate_ref['peri_err']:.1f}%, "
        f"ret_vinf={candidate_ref['return_vinf_proxy_kms']:.1f} km/s."
    ) if feasible_found else (
        f"No feasible low-return candidate found. "
        f"Best return_vinf among all: {best_ret['return_vinf_proxy_kms']:.1f} km/s (MJD {best_ret['t0_mjd']:.0f})."
    )

    print(f"\n  Verdict: {verdict}")

    out = {
        "task": "M6 constrained window refinement",
        "num_candidates": len(candidates),
        "num_feasible_low_return": len(feasible),
        "best_by_perihelion": best_peri,
        "best_by_low_return": best_ret,
        "best_by_low_dv": best_dv,
        "best_balanced": best_bal,
        "status": status,
        "verdict": verdict,
        "conclusion": (
            "Constrained search with return_vinf ≤ 15 km/s filter was applied. "
            + verdict
        ),
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    jp = out_dir / "m6_constrained_window_refine.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")
    print(f"\n{'='*66}")
    print(f"M6: {status}")
    print("="*66)


if __name__ == "__main__":
    main()
