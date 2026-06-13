"""
m5_no_lunar_fixed_date_deep_search.py
=====================================
Deepened no-lunar DSM search at the current formal M5 lunar anchor date.

The anchor date is read from m5_best_lunar_candidate_verify.json by default,
with optional `--t0` override.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import AU_KM, GM_SUN
from event_semantics import compute_earth_return_vinf
from horizons import fetch_sem_vectors
from lambert import orbital_elements_from_state, solve_lambert_universal
from mission_constraints import is_launch_mjd_in_window, mjd_to_date_str
from patched_conic import compute_patched_conic
from trajectory import interpolate_state_at_mjd
from units import day_to_sec, km_to_au

RESULTS = _REPO / "data" / "results"
VERIFY_JSON = RESULTS / "m5_best_lunar_candidate_verify.json"

V_RET_MAX = 15.0
PERI_TARGET_AU = 0.3
PERI_TOL = 0.03
DSM_MAX = 200.0

ELEM = compute_patched_conic(r_p_AU=PERI_TARGET_AU)


def _norm(v):
    return float(np.linalg.norm(v))


def _safe_lambert(r1, r2, tof_d, mu=GM_SUN, pg=True, lw=False):
    try:
        v1, v2, _ = solve_lambert_universal(r1, r2, day_to_sec(tof_d), mu, pg, lw)
        if np.any(np.isnan(v1)):
            return None
        return v1, v2
    except Exception:
        return None


def position_on_ellipse_at_time(theta0, t_days, a, e, mu=GM_SUN):
    n = math.sqrt(mu / (a ** 3))
    M = math.pi + n * day_to_sec(t_days)
    E_val = M
    for _ in range(100):
        dE = (M - (E_val - e * math.sin(E_val))) / (1.0 - e * math.cos(E_val))
        E_val += dE
        if abs(dE) < 1e-12:
            break
    tan_half = math.sqrt((1.0 + e) / (1.0 - e)) * math.tan(E_val / 2.0)
    nu = 2.0 * math.atan(tan_half)
    if nu < 0:
        nu += 2.0 * math.pi
    elif nu > 2.0 * math.pi:
        nu -= 2.0 * math.pi
    r_mag = a * (1.0 - e * math.cos(E_val))
    cos_p = math.cos(theta0 + math.pi)
    sin_p = math.sin(theta0 + math.pi)
    p_hat = np.array([cos_p, sin_p])
    q_hat = np.array([-sin_p, cos_p])
    cos_nu = math.cos(nu)
    sin_nu = math.sin(nu)
    r_vec = r_mag * (cos_nu * p_hat + sin_nu * q_hat)
    factor = math.sqrt(mu / (a * (1.0 - e * e)))
    v_vec = factor * (-sin_nu) * p_hat + factor * (e + cos_nu) * q_hat
    return r_vec, v_vec


def _default_t0() -> float:
    if VERIFY_JSON.exists():
        data = json.loads(VERIFY_JSON.read_text(encoding="utf-8"))
        return float(data["candidate"]["t0_mjd"])
    return 61065.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--t0", type=float, default=_default_t0())
    parser.add_argument(
        "--output",
        type=str,
        default=str(RESULTS / "m5_no_lunar_fixed_date_deep_search.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    t0 = float(args.t0)
    if not is_launch_mjd_in_window(t0):
        raise ValueError(f"t0={t0} ({mjd_to_date_str(t0)}) outside formal 2026 launch window")

    print("=" * 66)
    print(f"M5 no-lunar DSM deep search at t0={t0:.0f} ({mjd_to_date_str(t0)})")
    print("=" * 66)

    bd = fetch_sem_vectors(use_cache=True)
    rE0, vE0 = interpolate_state_at_mjd(bd, "Earth", t0)
    th0 = math.atan2(rE0[1], rE0[0])

    jd_arr = np.array(bd["Earth"]["jd_tdb"], dtype=float)
    mjd_end = jd_arr[-1] - 2400000.5

    _, v_aph = position_on_ellipse_at_time(th0, 0.0, ELEM.a, ELEM.e, GM_SUN)
    dep_vinf_t0 = _norm(v_aph - vE0)

    tof1_list = list(range(20, 310, 5))
    tof2_list = list(range(30, 350, 5))
    branches = [(True, False), (True, True), (False, False)]

    total = len(tof1_list) * len(tof2_list) * len(branches)
    print(f"  approx combinations: {total}")
    print(f"  dep_vinf_actual: {dep_vinf_t0:.4f} km/s")

    t_start = time.time()
    candidates = []
    evaled = 0

    for tof1 in tof1_list:
        t_dsm = t0 + tof1
        if t_dsm > mjd_end - 30:
            continue
        r_DSM, v_coast = position_on_ellipse_at_time(th0, tof1, ELEM.a, ELEM.e, GM_SUN)

        for tof2 in tof2_list:
            t_ret = t_dsm + tof2
            if t_ret > mjd_end:
                continue

            for pg, lw in branches:
                evaled += 1
                try:
                    rEret, vEret = interpolate_state_at_mjd(bd, "Earth", t_ret)
                except Exception:
                    continue
                leg2 = _safe_lambert(r_DSM, rEret, tof2, pg=pg, lw=lw)
                if leg2 is None:
                    continue
                v2dep, v2arr = leg2

                dsm_dv = _norm(v2dep - v_coast)
                if dsm_dv > DSM_MAX:
                    continue
                ret_vinf = _norm(v2arr - vEret)
                if ret_vinf > 50:
                    continue

                _, _, rp_km, _, _ = orbital_elements_from_state(r_DSM, v2dep, GM_SUN)
                rp_au = km_to_au(rp_km)
                overall_peri = min(rp_au, PERI_TARGET_AU)
                peri_err = abs(overall_peri - PERI_TARGET_AU)
                ret_brake = max(0.0, ret_vinf - V_RET_MAX)
                total_dv = dep_vinf_t0 + dsm_dv + ret_brake
                fair = bool(peri_err <= PERI_TOL and ret_vinf <= V_RET_MAX)

                candidates.append(
                    {
                        "t0_mjd": t0,
                        "t0_date": mjd_to_date_str(t0),
                        "tof1_days": tof1,
                        "tof2_days": tof2,
                        "r_DSM_AU": round(km_to_au(_norm(r_DSM)), 4),
                        "departure_vinf_kms": round(dep_vinf_t0, 4),
                        "dsm_delta_v_kms": round(dsm_dv, 4),
                        "return_vinf_kms": round(ret_vinf, 4),
                        "return_braking_proxy_kms": round(ret_brake, 4),
                        "perihelion_AU": round(overall_peri, 6),
                        "peri_err_AU": round(peri_err, 6),
                        "total_dv_proxy_kms": round(total_dv, 4),
                        "fair": fair,
                    }
                )

    fair = [c for c in candidates if c["fair"]]
    best_valid = min(fair, key=lambda c: c["total_dv_proxy_kms"]) if fair else None
    best_near_miss = min(candidates, key=lambda c: (c["return_vinf_kms"], c["peri_err_AU"])) if candidates and not fair else None

    out = {
        "task": "M5 no-lunar DSM deep search at fixed legal date",
        "classification": "ACTUAL_RESULT" if best_valid is not None else "FINITE_SEARCH_NEG",
        "status": "valid_found" if best_valid is not None else "finite_search_negative",
        "t0_mjd": t0,
        "t0_date": mjd_to_date_str(t0),
        "launch_window_valid": True,
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
        "best_valid": best_valid,
        "best_near_miss": best_near_miss,
        "runtime_sec": round(time.time() - t_start, 3),
    }

    out_path = Path(args.output)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    csv_path = out_path.with_suffix(".csv")
    if candidates:
        import csv
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(candidates[0].keys()))
            w.writeheader()
            w.writerows(candidates)

    print(f"Saved: {out_path}")
    print(f"Saved: {csv_path}")
    print(f"valid_fair_candidates = {len(fair)}")
    if best_valid:
        print(
            f"best_valid total={best_valid['total_dv_proxy_kms']:.4f} "
            f"ret_vinf={best_valid['return_vinf_kms']:.4f} "
            f"dsm={best_valid['dsm_delta_v_kms']:.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
