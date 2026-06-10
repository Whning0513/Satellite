"""
m5_lunar_budget_recompute.py
============================
Recomputes the M5 lunar-assisted candidate budget, but FIRST checks
whether the trajectory actually reaches Earth return.

If no valid Earth-return event exists, return quantities are set to
null and no total_dv_proxy / saving ratio can be computed.

Output: data/results/m5_lunar_budget_recomputed.json
"""

import json, os, sys, math
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import R_MOON, AU_KM
from trajectory import DesignParams, solve_trajectory
from event_semantics import compute_earth_return_vinf
from horizons import fetch_sem_vectors

V_RET_MAX = 15.0


def main():
    print("=" * 66)
    print("M5 lunar budget recompute (with return-event check)")
    print("=" * 66)

    # Run trajectory
    body_data = fetch_sem_vectors(use_cache=True)
    params = DesignParams(61066.0, R_MOON + 500.0, "trailing", 0.3 * AU_KM)
    traj = solve_trajectory(params, body_data, verbose=False)

    dep_vinf = traj.v_inf_earth
    swingby_dv = traj.swingby.dv_mag if traj.swingby else 0.0
    peri_au = traj.r_p_achieved_km / AU_KM

    print(f"  t0_mjd:         61066.0")
    print(f"  dep_vinf:       {dep_vinf:.4f} km/s")
    print(f"  swingby dv:     {swingby_dv:.4f} km/s")
    print(f"  perihelion:     {peri_au:.4f} AU")

    # Check return event
    t_ret_mjd = 61066.0 + traj.t_total_days
    r_sun_ret, v_sun_ret = body_data["Sun"], None  # placeholder
    # Get actual states
    from trajectory import interpolate_state_at_mjd
    r_sun_ret, v_sun_ret = interpolate_state_at_mjd(body_data, "Sun", t_ret_mjd)
    r_earth_ret, v_earth_ret = interpolate_state_at_mjd(body_data, "Earth", t_ret_mjd)

    # convert to heliocentric for event check
    v_sc_helio = traj.v_final  # already in SSB frame
    v_earth_helio = traj.v_earth_final
    r_sc_helio = traj.r_final

    # Use event_semantics to check
    return_check = compute_earth_return_vinf(
        r_sc_helio, v_sc_helio,
        r_earth_ret, v_earth_ret)

    if return_check["valid_return_event"]:
        ret_vinf = return_check["return_vinf_kms"]
        v_reentry = return_check["reentry_speed_kms"]
        print(f"  return_vinf:    {ret_vinf:.4f} km/s (VALID Earth return)")
    else:
        ret_vinf = None
        v_reentry = None
        print(f"  return_vinf:    INVALID — {return_check['reason']}")

    print()

    # ── Budget (only if return is valid) ──
    if ret_vinf is not None:
        lunar_residual = 0.0
        return_brake = max(0, ret_vinf - V_RET_MAX)
        total_dv = dep_vinf + lunar_residual + return_brake
        budget_valid = True
    else:
        lunar_residual = None
        return_brake = None
        total_dv = None
        budget_valid = False

    lunar_params = {
        "t0_mjd": 61066.0,
        "return_vinf_valid": return_check["valid_return_event"],
        "return_event_distance_km": return_check["distance_to_earth_km"],
        "return_event_type": return_check["event_type"],
        "return_vinf_kms_old_claimed": float(traj.v_rel_earth),
        "swingby_delta_v_kms": round(float(swingby_dv), 4),
        "perihelion_AU": round(float(peri_au), 4),
        "dep_vinf_actual_kms": round(float(dep_vinf), 4),
        "note_on_return_vinf": (
            "The trajectory ends at perihelion (~0.28 AU), not at Earth. "
            "The OLD claimed 'return_vinf' = 77.88 km/s is a heliocentric "
            "velocity difference at different positions, NOT an Earth reentry speed."
        ),
    }

    out = {
        "task": "M5 lunar budget recompute (with return-event semantics)",
        "budget_function": "total = departure_vinf + residual + max(0, return_vinf - 15); valid only if Earth return",
        "params": lunar_params,
        "budget_valid": budget_valid,
        "budget": {
            "departure_vinf_kms": round(float(dep_vinf), 4),
            "launch_proxy_kms": round(float(dep_vinf), 4),
            "lunar_residual_kms": round(float(lunar_residual), 4) if lunar_residual is not None else None,
            "return_vinf_kms": ret_vinf,
            "return_vinf_old_invalid_kms": round(float(traj.v_rel_earth), 4),
            "return_braking_proxy_kms": round(float(return_brake), 4) if return_brake is not None else None,
            "total_dv_proxy_kms": round(float(total_dv), 4) if total_dv is not None else None,
        },
        "note": (
            "Gravity-assist swingby is free. "
            "Return_vinf is NULL because the trajectory does not reach Earth. "
            "No valid total_dv_proxy or saving ratio can be computed from this candidate."
        ),
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    jp = out_dir / "m5_lunar_budget_recomputed.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(f"  Budget components:")
    print(f"    departure_vinf:    {dep_vinf:.4f} km/s")
    print(f"    return_vinf:       {ret_vinf} (valid: {return_check['valid_return_event']})")
    print(f"    total_dv_proxy:    {total_dv}")
    print(f"\nSaved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
