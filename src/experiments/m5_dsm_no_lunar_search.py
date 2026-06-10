"""
m5_dsm_no_lunar_search.py
=========================
True no-lunar DSM baseline — sample DSM points along the transfer ellipse.

Strategy
--------
1. The spacecraft departs Earth on the standard patched-conic transfer
   orbit to r_p = 0.3 AU.  The orbit is a Keplerian ellipse with known
   (a, e, r_p, r_a, T).
2. For any time-of-flight from departure, we solve Kepler's equation to
   get the spacecraft's (r, v) on that ellipse *before* the DSM.
3. At that point, apply a DSM and Lambert-transfer from that position to
   Earth at a later return time.
4. DSM Δv = ∥v_lambert - v_coast∥.

This reduces the free parameters to (t0, tof_before_DSM, tof_after_DSM);
the DSM position is determined by the physical orbit, not a free grid
parameter.  The patched-conic orbit naturally reaches r_p = 0.3 AU.

Output: data/results/m5_dsm_no_lunar_search.json
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
from horizons import fetch_sem_vectors
from patched_conic import compute_patched_conic

# ── Constraints ──
V_RET_MAX = 15.0
V_DEP_MAX = 20.0
PERI_TARGET_AU = 0.3
PERI_TOL = 0.03
PERI_TOL_NEAR = 0.05
DSM_MAX = 150.0  # skip insane candidates

# ── Patched-conic orbit (r_p = 0.3 AU) ──
ELEM = compute_patched_conic(r_p_AU=PERI_TARGET_AU)
V_INF_DEP = abs(ELEM.delta_v)   # 9.55 km/s
T_HALF = ELEM.dt_flight_days    # 95.71 days
T_PERIOD = 2 * T_HALF           # 191.4 days
A_AU = ELEM.a / AU_KM           # 0.65 AU
E_ECC = ELEM.e                  # 0.538...
R_APO = ELEM.r_1 / AU_KM        # 1.0 AU (aphelion)


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


def kepler_anomaly(M, e, tol=1e-12, max_iter=100):
    """Solve Kepler's equation M = E - e*sin(E) for the eccentric anomaly E."""
    E = M
    for _ in range(max_iter):
        dE = (M - (E - e * math.sin(E))) / (1.0 - e * math.cos(E))
        E += dE
        if abs(dE) < tol:
            break
    return E


def position_on_ellipse_at_time(theta0, t_days, a, e, mu=GM_SUN):
    """Return heliocentric (r, v) at time t after passing through aphelion
    at heliocentric angle theta0.

    Orbit is a Kepler ellipse with semi-major axis a (km) and eccentricity e.
    True anomaly ν = 0 at perihelion, ν = π at aphelion.
    At t = 0 the spacecraft is at aphelion (ν = π, Earth departure position θ0).

    Parameters
    ----------
    theta0 : float — heliocentric angle of Earth at t0
    t_days : float — time since aphelion departure (days)
    a : float — semi-major axis (km)
    e : float — eccentricity
    mu : float — gravitational parameter (km³/s²)

    Returns
    -------
    (r_vec, v_vec) — heliocentric position (km) and velocity (km/s)
    """
    # Mean motion
    n = math.sqrt(mu / (a ** 3))

    # At t=0, the spacecraft is at aphelion with E = M = π.
    M = math.pi + n * day_to_sec(t_days)

    # Eccentric anomaly (Kepler's equation: M = E - e sin E)
    E = M  # initial guess
    for _ in range(100):
        dE = (M - (E - e * math.sin(E))) / (1.0 - e * math.cos(E))
        E += dE
        if abs(dE) < 1e-12:
            break

    # True anomaly
    tan_half = math.sqrt((1.0 + e) / (1.0 - e)) * math.tan(E / 2.0)
    nu = 2.0 * math.atan(tan_half)
    if nu < 0:
        nu += 2.0 * math.pi
    elif nu > 2.0 * math.pi:
        nu -= 2.0 * math.pi

    # Distance from Sun
    r_mag = a * (1.0 - e * math.cos(E))

    # Perifocal frame: p̂ = unit vector from Sun toward perihelion (= θ0 + π)
    #                  q̂ = p̂ rotated 90° CCW (= direction of motion from peri)
    cos_p = math.cos(theta0 + math.pi)
    sin_p = math.sin(theta0 + math.pi)
    p_hat = np.array([cos_p, sin_p])     # periapsis direction
    q_hat = np.array([-sin_p, cos_p])    # periapsis + 90° CCW

    # Position: r = r_mag * (cos ν * p̂ + sin ν * q̂)
    cos_nu = math.cos(nu)
    sin_nu = math.sin(nu)
    r_vec = r_mag * (cos_nu * p_hat + sin_nu * q_hat)

    # Velocity in perifocal frame (Vallado eq. 2-127,2-128):
    #   v = sqrt(μ / p) * (-sin ν * p̂ + (e + cos ν) * q̂)
    #   p = a * (1 - e²)
    factor = math.sqrt(mu / (a * (1.0 - e * e)))
    v_peri_p = factor * (-sin_nu)       # component along p̂ (periapsis direction)
    v_peri_q = factor * (e + cos_nu)    # component along q̂ (perp to p̂, CCW)

    # Heliocentric: v = v_peri_p * p̂ + v_peri_q * q̂
    v_vec = v_peri_p * p_hat + v_peri_q * q_hat

    return r_vec, v_vec


def evaluate_one(t0_days, tof1, tof2, body_data,
                 pg=True, lw=False,
                 _dep_vinf=None, _vE0=None, _th0=None):
    """Evaluate one two-impulse candidate.

    Parameters
    ----------
    t0_days : MJD of launch
    tof1 : float — days from launch to DSM (along ellipse)
    tof2 : float — days from DSM to Earth return
    body_data : dict
    pg, lw : Lambert branch
    _dep_vinf : pre-computed departure v_inf (km/s)
    _vE0 : pre-computed Earth velocity at t0
    _th0 : pre-computed Earth angle at t0

    Returns
    -------
    dict or None
    """
    # Earth state at t0
    if _vE0 is None or _th0 is None:
        try:
            rE0, vE0 = interpolate_state_at_mjd(body_data, "Earth", t0_days)
        except Exception:
            return None
        th0 = math.atan2(rE0[1], rE0[0])
    else:
        vE0, th0 = _vE0, _th0

    # Compute ACTUAL departure v_inf from ellipse aphelion velocity
    # (vector difference from Earth's actual heliocentric velocity,
    #  not from the patched-conic circular-orbit approximation)
    if _dep_vinf is None:
        _, v_aphelion = position_on_ellipse_at_time(th0, 0.0, ELEM.a, ELEM.e, GM_SUN)
        dep_vinf = _norm(v_aphelion - vE0)
    else:
        dep_vinf = _dep_vinf

    # Position at DSM point (along the transfer ellipse, tof1 after departure)
    r_DSM, v_coast = position_on_ellipse_at_time(th0, tof1, ELEM.a, ELEM.e, GM_SUN)

    # Earth at return
    t_ret = t0_days + tof1 + tof2
    try:
        rEret, vEret = interpolate_state_at_mjd(body_data, "Earth", t_ret)
    except Exception:
        return None

    # Lambert: DSM → Earth
    leg2 = _safe_lambert(r_DSM, rEret, tof2, GM_SUN, pg, lw)
    if leg2 is None:
        return None
    v_arr, v_Earr = leg2

    # DSM Δv = ∥v_lambert - v_coast_at_DSM∥
    dsm_dv = _norm(v_arr - v_coast)
    if dsm_dv > DSM_MAX:
        return None

    # Return v_inf
    ret_vinf = _norm(v_Earr - vEret)
    if ret_vinf > 50:
        return None

    # Perihelion of leg 2 orbit
    _, _, rp2_km, _, _ = orbital_elements_from_state(r_DSM, v_arr, GM_SUN)
    rp2_au = km_to_au(rp2_km)

    # Overall mission perihelion = min(ellipse r_p, leg2 r_p)
    overall_peri = min(PERI_TARGET_AU, rp2_au)
    peri_err = abs(overall_peri - PERI_TARGET_AU)

    # ── Budget proxy ──
    launch_proxy = dep_vinf
    ret_brake = max(0.0, ret_vinf - V_RET_MAX)
    total_dv = launch_proxy + dsm_dv + ret_brake

    # ── Classification ──
    fair = (peri_err <= PERI_TOL and ret_vinf <= V_RET_MAX
            and dep_vinf <= V_DEP_MAX)
    near = (peri_err <= PERI_TOL_NEAR and ret_vinf <= 20.0
            and dep_vinf <= V_DEP_MAX)

    return {
        "t0_mjd": float(round(t0_days, 1)),
        "dsm_mjd": float(round(t0_days + tof1, 1)),
        "return_mjd": float(round(t_ret, 1)),
        "tof1_days": float(round(tof1, 2)),
        "tof2_days": float(round(tof2, 2)),
        "r_DSM_AU": float(round(km_to_au(_norm(r_DSM)), 4)),
        "departure_vinf_kms": round(dep_vinf, 4),
        "launch_proxy_kms": round(dep_vinf, 4),
        "dsm_delta_v_kms": round(float(dsm_dv), 4),
        "return_vinf_kms": round(float(ret_vinf), 4),
        "return_braking_proxy_kms": round(ret_brake, 4),
        "perihelion_AU": round(float(overall_peri), 6),
        "peri_err_AU": round(float(peri_err), 6),
        "leg2_rp_AU": round(float(rp2_au), 6),
        "total_dv_proxy_kms": round(float(total_dv), 4),
        "lambert_prograde": bool(pg),
        "lambert_long_way": bool(lw),
        "fair": bool(fair),
        "near_feasible": bool(near),
    }


def main():
    print("=" * 66)
    print("M5 DSM no-lunar — ellipse-sampled DSM points")
    print("=" * 66)
    print(f"  v_inf_dep variable (per t0) = 9.55-10.21 km/s (actual ellipse-Earth)")
    print(f"  Orbit: a={A_AU:.4f} AU, e={E_ECC:.5f}")
    print(f"  T_half={T_HALF:.2f} d, T_period={T_PERIOD:.2f} d")
    print()

    body_data = fetch_sem_vectors(use_cache=True)
    jd_arr = np.array(body_data["Earth"]["jd_tdb"], dtype=float)
    mjd_end = jd_arr[-1] - 2400000.5

    # ── Focused launch dates ──
    t0s = sorted(set([
        61041., 61051., 61061., 61066., 61071., 61081.,
        61100., 61125., 61140., 61154., 61170., 61185.,
        61200., 61213., 61225., 61250., 61270., 61290.,
        61310., 61330., 61350., 61370., 61390.,
    ]))

    # ── tof1 (days to DSM) ──
    # Sweep the full orbit: from early departure through perihelion
    # and back toward aphelion
    tof1_list = list(range(20, 310, 10))  # 20–300 days, step 10

    # ── tof2 (days from DSM to Earth return) ──
    tof2_list = list(range(30, 300, 15))  # 30–285 days, step 15

    # ── Lambert branches ──
    branches = [(True, False), (True, True), (False, False)]

    n_expected = len(t0s) * len(tof1_list) * len(tof2_list) * len(branches)
    print(f"  t0:     {len(t0s)}")
    print(f"  tof1:   {len(tof1_list)} ({tof1_list[0]}-{tof1_list[-1]} d)")
    print(f"  tof2:   {len(tof2_list)} ({tof2_list[0]}-{tof2_list[-1]} d)")
    print(f"  branch: {len(branches)}")
    print(f"  Total: ~{n_expected:,}\n")

    t_start = time.time()
    candidates = []
    evaluated = 0

    for t0 in t0s:
        if t0 > mjd_end - 30:
            continue

        # Pre-compute actual departure v_inf for this t0
        try:
            rE0, vE0 = interpolate_state_at_mjd(body_data, "Earth", t0)
            th0 = math.atan2(rE0[1], rE0[0])
            _, v_aphelion = position_on_ellipse_at_time(
                th0, 0.0, ELEM.a, ELEM.e, GM_SUN)
            dep_vinf_t0 = _norm(v_aphelion - vE0)
        except Exception as e:
            print(f"  [SKIP t0={t0:.0f}] fail: {e}")
            continue

        for tof1 in tof1_list:
            t_dsm = t0 + tof1
            if t_dsm > mjd_end:
                continue

            for tof2 in tof2_list:
                t_ret = t0 + tof1 + tof2
                if t_ret > mjd_end:
                    continue

                for pg, lw in branches:
                    evaluated += 1
                    c = evaluate_one(t0, tof1, tof2, body_data, pg, lw,
                                     _dep_vinf=dep_vinf_t0, _vE0=vE0, _th0=th0)
                    if c is not None:
                        candidates.append(c)

        # Progress
        if len(t0s) > 5 and t0s.index(t0) > 0 and t0s.index(t0) % 5 == 0:
            print(f"  t0={t0:.0f}: {len(candidates)} candidates "
                  f"({time.time()-t_start:.0f}s)")

    t_elap = time.time() - t_start

    # ── Deduplicate (same t0, tof1, tof2 → keep the Lambert branch that
    #     gave the lowest DSM Δv) ──
    seen = {}
    for c in candidates:
        key = (round(c["t0_mjd"], 1), round(c["tof1_days"], 1),
               round(c["tof2_days"], 1))
        if key not in seen or c["dsm_delta_v_kms"] < seen[key]["dsm_delta_v_kms"]:
            seen[key] = c
    candidates = list(seen.values())

    # ── Sort & classify ──
    candidates.sort(key=lambda c: c["total_dv_proxy_kms"])
    fair = [c for c in candidates if c["fair"]]
    near = [c for c in candidates if c["near_feasible"]]

    print(f"\n  Evaluated:        {evaluated:,}")
    print(f"  DSM candidates:   {len(candidates)}")
    print(f"  Strict fair:      {len(fair)}")
    print(f"  Near-feasible:    {len(near)}")
    print(f"  Runtime:          {t_elap:.0f}s")
    print()

    for label, lst, src in [
            ("Top 10 by total Δv", 10, candidates),
            ("Top 5 fair", 5, fair),
            ("Top 5 near-feasible", 5, near),
    ]:
        if not src:
            continue
        print(f"  {label}:")
        for i, c in enumerate(src[:lst]):
            r_info = f"r_DSM={c['r_DSM_AU']:.2f}AU"
            print(f"    #{i+1}: t0={c['t0_mjd']:.0f} "
                  f"tof1={c['tof1_days']:.0f}/{c['tof2_days']:.0f}d "
                  f"{r_info}")
            print(f"         v_inf_d={c['departure_vinf_kms']:.2f} "
                  f"dsm={c['dsm_delta_v_kms']:.2f} "
                  f"v_inf_r={c['return_vinf_kms']:.2f} "
                  f"peri={c['perihelion_AU']:.4f} "
                  f"tot={c['total_dv_proxy_kms']:.2f}")
            print(f"         fair={c['fair']} near={c['near_feasible']}")
        print()

    # ── Best picks ──
    def bal_score(c):
        return (abs(c['perihelion_AU'] - PERI_TARGET_AU) * 100
                + max(0, c['return_vinf_kms'] - V_RET_MAX) * 2
                + c['dsm_delta_v_kms'] * 0.5)

    best_peri = (min(candidates, key=lambda c: abs(c['perihelion_AU'] - PERI_TARGET_AU))
                 if candidates else None)
    best_vinf = (min(candidates, key=lambda c: abs(c['return_vinf_kms'] - V_RET_MAX))
                 if candidates else None)
    best_dv = (min(candidates, key=lambda c: c['total_dv_proxy_kms'])
               if candidates else None)
    best_bal = (min(candidates, key=bal_score) if candidates else None)

    # ── Save (top 2000 candidates) ──
    to_save = candidates[:min(2000, len(candidates))]

    summary = {
        "task": "M5 DSM no-lunar — ellipse-sampled DSM",
        "strategy": (
            "depart on patched-conic r_p=0.3 AU ellipse, solve Kepler eq "
            "for DSM position at tof1, then Lambert DSM -> Earth"
        ),
        "config": {
            "orbit_a_AU": float(round(A_AU, 4)),
            "orbit_e": float(round(E_ECC, 6)),
            "departure_vinf_method": "actual (ellipse_v_aphelion - v_Earth)",
            "t0_count": len(t0s),
            "tof1_steps": len(tof1_list),
            "tof2_steps": len(tof2_list),
        },
        "num_evaluated": evaluated,
        "num_candidates": len(candidates),
        "num_fair": len(fair),
        "num_near_feasible": len(near),
        "runtime_s": round(t_elap, 1),
        "best_strict_fair": fair[0] if fair else None,
        "best_near_feasible": (min(near, key=lambda c: c["total_dv_proxy_kms"])
                               if near else None),
        "best_by_perihelion": best_peri,
        "best_by_return_vinf": best_vinf,
        "best_by_total_dv": best_dv,
        "best_balanced": best_bal,
        "all_candidates": to_save,
    }

    if fair:
        summary["status"] = "fair_baseline_found"
    elif near:
        summary["status"] = "near_feasible_found"
    elif candidates:
        summary["status"] = "no_usable_baseline"
    else:
        summary["status"] = "no_candidates"

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    jp = out_dir / "m5_dsm_no_lunar_search.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"  Saved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
