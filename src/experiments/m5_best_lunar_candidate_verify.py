"""
m5_best_lunar_candidate_verify.py
==================================
Verifies the current best legal-window lunar Earth-return candidate.

The script prefers the best row from the active complete-return search JSON and
otherwise falls back to the current legal anchor at t0=61065, side=trailing,
r_m=1837.4 km.
"""

import json, os, sys, math
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import GM_SUN, GM_EARTH, GM_MOON, AU_KM, R_MOON, DT_MAIN, V_ESCAPE_EARTH
from units import km_to_au
from trajectory import DesignParams, solve_trajectory, interpolate_state_at_mjd
from nbody import propagate_nbody
from event_semantics import compute_earth_return_vinf, classify_event
from horizons import fetch_sem_vectors
from mission_constraints import is_launch_mjd_in_window, mjd_to_date_str

EARTH_THRESHOLD_KM = 1.5e6
SEARCH_JSON = _REPO / "data" / "results" / "m5_complete_lunar_return_search.json"


def _norm(v):
    return float(np.linalg.norm(v))


def main():
    print("=" * 66)
    print("M5 best lunar candidate verification")
    print("=" * 66)

    bd = fetch_sem_vectors(use_cache=True)

    if SEARCH_JSON.exists():
        search = json.loads(SEARCH_JSON.read_text(encoding="utf-8"))
        best = search.get("best_valid")
    else:
        best = None

    if best:
        t0 = float(best["t0_mjd"])
        side = best["side"]
        rm = float(best["r_m_km"])
    else:
        t0 = 61065.0
        side = "trailing"
        rm = R_MOON + 100.0

    print(f"  Best candidate: t0={t0:.0f}, side={side}, r_m={rm:.0f} km")
    print()

    # ── Phase 1: Standard trajectory ──
    print("[1] Solving trajectory...")
    params = DesignParams(t0, rm, side, 0.3 * AU_KM)
    traj = solve_trajectory(params, bd, verbose=False, dt_integrate=DT_MAIN)
    print(f"  success={traj.success}")
    print(f"  t_total={traj.t_total_days:.2f} days")
    print(f"  dep_vinf={traj.v_inf_earth:.4f} km/s")
    print(f"  v_launch={traj.v_launch:.4f} km/s")
    print(f"  r_p_achieved={km_to_au(traj.r_p_achieved_km):.4f} AU")
    print(f"  swingby_dv={traj.swingby.dv_mag if traj.swingby else 0:.4f} km/s")

    # ── Phase 2: Extended propagation ──
    print("\n[2] Extended propagation to Earth return...")
    t_end = t0 + traj.t_total_days
    rs, vs = interpolate_state_at_mjd(bd, "Sun", t_end)
    rm_, vm_ = interpolate_state_at_mjd(bd, "Moon", t_end)
    r = [rs.copy(), traj.r_earth_final.copy(), rm_.copy(), traj.r_final.copy()]
    v = [vs.copy(), traj.v_earth_final.copy(), vm_.copy(), traj.v_final.copy()]
    gm = [GM_SUN, GM_EARTH, GM_MOON, 0.0]

    best_dist = 1e12; best_day = -1; best_mjd = t_end
    best_sc = None; best_vsc = None; best_re = None; best_ve = None
    best_moon = None; min_sun = 1e12
    n_days = 500

    for day in range(1, n_days + 1):
        r, v = propagate_nbody(r, v, 86400.0, gm, 4, dt_internal=3600.0)
        cur_mjd = t_end + day
        try:
            re, ve = interpolate_state_at_mjd(bd, "Earth", cur_mjd)
            r[1] = re.copy(); v[1] = ve.copy()
            rm2, vm2 = interpolate_state_at_mjd(bd, "Moon", cur_mjd)
            r[2] = rm2.copy(); v[2] = vm2.copy()
        except: pass
        sc = r[3]; d = _norm(sc - r[1]); ds = _norm(sc - r[0])
        if ds < min_sun: min_sun = ds
        if d < best_dist:
            best_dist = d; best_day = day; best_mjd = cur_mjd
            best_sc = sc.copy(); best_vsc = v[3].copy()
            best_re = r[1].copy(); best_ve = v[1].copy()
            best_moon = r[2].copy()
        if best_dist < EARTH_THRESHOLD_KM and d > best_dist * 2:
            break
    # Get Sun at closest
    try:
        rs_best, vs_best = interpolate_state_at_mjd(bd, "Sun", best_mjd)
    except:
        rs_best, vs_best = rs, vs

    # ── Phase 3: Event verification ──
    print(f"\n[3] Event verification at closest approach (day {best_day}, MJD {best_mjd:.2f})...")
    v_sc_h = best_vsc - vs_best
    v_e_h = best_ve - vs_best
    r_sc_h = best_sc - rs_best
    return_vinf = _norm(v_sc_h - v_e_h)
    solar_energy = 0.5 * _norm(v_sc_h)**2 - GM_SUN / _norm(r_sc_h)
    v_esc_solar = math.sqrt(2.0 * GM_SUN / _norm(r_sc_h))

    dist_moon = _norm(best_sc - best_moon)
    event_type = classify_event(best_sc, best_re, rs_best)
    check = compute_earth_return_vinf(best_sc, best_vsc, best_re, best_ve)

    print(f"  distance_to_earth:  {best_dist:.0f} km ({best_dist/AU_KM:.6f} AU)")
    print(f"  threshold_km:       {EARTH_THRESHOLD_KM:.0f}")
    print(f"  valid_return_event: {check['valid_return_event']}")
    print(f"  event_type:         {event_type}")
    print(f"  distance_to_moon:   {dist_moon:.0f} km")
    print(f"  r_sc_helio:         {km_to_au(_norm(r_sc_h)):.4f} AU")
    print(f"  v_sc_helio_norm:    {_norm(v_sc_h):.2f} km/s")
    print(f"  v_earth_helio_norm: {_norm(v_e_h):.2f} km/s")
    print(f"  return_vinf:        {return_vinf:.4f} km/s")
    print(f"  solar_specific_E:   {solar_energy:.0f} km^2/s^2")
    print(f"  perihelion_AU:      {km_to_au(min_sun):.4f} AU")

    # ── Phase 4: Budget breakdown ──
    print(f"\n[4] Budget breakdown:")
    launch_equiv = math.sqrt(V_ESCAPE_EARTH**2 + traj.v_inf_earth**2)
    dep_vinf = float(traj.v_inf_earth)
    swingby = float(traj.swingby.dv_mag) if traj.swingby else 0.0
    ret_brake = max(0, return_vinf - 15.0)

    budget = {
        "departure_vinf_kms": round(dep_vinf, 4),
        "launch_equivalent_kms": round(launch_equiv, 4),
        "lunar_swingby_residual_kms": round(swingby, 4),
        "lunar_swingby_is_free_gravity_assist": True,
        "return_vinf_kms": round(return_vinf, 4),
        "return_braking_proxy_kms": round(ret_brake, 4),
    }
    budget["total_dv_proxy_vinf_basis"] = round(dep_vinf + 0.0 + ret_brake, 4)
    # Launch-equivalent: if we include surface-to-orbit
    budget["total_dv_proxy_launch_equivalent_basis"] = round(
        launch_equiv + 0.0 + ret_brake, 4)
    budget["note"] = (
        "vinf_basis uses hyperbolic excess speed (comparable to DSM no-lunar). "
        "launch_equivalent includes surface-to-orbit ascent cost "
        f"= sqrt(V_esc^2 + vinf^2) = {launch_equiv:.4f} km/s"
    )

    for k, v in budget.items():
        if k != "note":
            print(f"  {k:<40s}: {v}")

    print(f"\n  {budget['note']}")

    # ── Save ──
    formal_ok = bool(check["valid_return_event"] and is_launch_mjd_in_window(t0))
    classification = "ACTUAL_RESULT" if formal_ok else "INVALID_FORMAL_WINDOW_OR_EVENT"
    out = {
        "task": "M5 best lunar candidate verification",
        "candidate": {
            "t0_mjd": t0,
            "t0_date": mjd_to_date_str(t0),
            "launch_window_valid": is_launch_mjd_in_window(t0),
            "side": side,
            "r_m_km": round(rm, 1),
        },
        "trajectory_summary": {
            "t_total_days": round(traj.t_total_days, 2),
            "r_p_achieved_AU": round(km_to_au(traj.r_p_achieved_km), 6),
            "swingby_dv_mag": round(swingby, 4),
        },
        "event_check": {
            "valid_return_event": check["valid_return_event"],
            "distance_to_earth_km": round(best_dist, 1),
            "distance_to_earth_AU": round(best_dist / AU_KM, 6),
            "event_type": event_type,
            "distance_to_moon_km": round(dist_moon, 1),
            "return_epoch_mjd": round(best_mjd, 2),
        },
        "state_at_return": {
            "r_sc_helio_AU": round(km_to_au(_norm(r_sc_h)), 6),
            "v_sc_helio_norm_kms": round(_norm(v_sc_h), 4),
            "v_earth_helio_norm_kms": round(_norm(v_e_h), 4),
            "return_vinf_kms": round(return_vinf, 4),
            "solar_specific_energy_km2_s2": round(solar_energy, 2),
            "solar_bound": solar_energy < 0,
        },
        "budget": budget,
        "classification": classification,
        "formal_result_eligible": formal_ok,
        "reason": None if formal_ok else (
            f"launch_window_valid={is_launch_mjd_in_window(t0)}, "
            f"valid_return_event={check['valid_return_event']}"
        ),
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    jp = out_dir / "m5_best_lunar_candidate_verify.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
