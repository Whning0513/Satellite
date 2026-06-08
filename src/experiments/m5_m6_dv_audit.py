"""
m5_m6_dv_audit.py
=================
M5/M6 Δv consistency audit — full vector audit, fairness check, return angle.

Output: data/results/m5_m6_dv_audit.json
"""

import json, os, sys, numpy as np, math
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import GM_SUN, AU_KM, R_MOON, V_ESCAPE_EARTH, V_INF_MAX, V_EARTH_ORBIT
from units import km_to_au
from trajectory import DesignParams, solve_trajectory
from patched_conic import compute_patched_conic
from horizons import fetch_sem_vectors


def _v(v):
    return np.array(v, dtype=float)
def _norm(v):
    return float(np.linalg.norm(_v(v)))
def _fmt(v):
    return [round(float(x), 4) for x in _v(v)]
def _angle_deg(v1, v2):
    c = np.dot(_v(v1), _v(v2)) / (_norm(v1)*_norm(v2)+1e-30)
    return float(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))


def audit_lunar_case(t0_mjd, label, body_data, rp_design=0.3):
    params = DesignParams(t0_mjd=t0_mjd, r_m=R_MOON+500, side="trailing", r_p=rp_design*AU_KM)
    traj = solve_trajectory(params, body_data, verbose=False)

    r_earth0, v_earth0 = traj.r_earth_t0, traj.v_earth_t0
    v_moon = traj.v_moon_t0
    v_rocket_pre = traj.v_at_moon
    v_rocket_post = traj.v_post_swingby
    v_inf_in = _v(v_rocket_pre) - _v(v_moon)
    v_inf_out = _v(v_rocket_post) - _v(v_moon)
    r_earth_final, v_earth_final = traj.r_earth_final, traj.v_earth_final
    v_rocket_final = traj.v_final
    v_rel_return_vec = _v(v_rocket_final) - _v(v_earth_final)
    v_rel_return_norm = _norm(v_rel_return_vec)
    dv_reentry = max(0, v_rel_return_norm - V_INF_MAX)

    # Return angle: how much is rocket opposite to Earth?
    return_angle = _angle_deg(v_rocket_final, v_earth_final)

    # Check: scalar speed difference vs vector difference
    scalar_diff = abs(_norm(v_rocket_final) - _norm(v_earth_final))

    earth_dep_speed = _norm(v_earth0)

    warnings = []
    if earth_dep_speed < 20 or earth_dep_speed > 40:
        warnings.append(f"earth_speed={earth_dep_speed:.1f} km/s expected ~29.8")
    if v_rel_return_norm > 100:
        warnings.append(f"v_rel_return={v_rel_return_norm:.1f} > 100 km/s")
    # Vector vs scalar difference is expected when velocity vectors are non-parallel
    # Correct formula: v_rel = |v_rocket - v_earth| (vector diff, used below)
    # Incorrect formula: |v_rocket| - |v_earth| (scalar diff, NOT used)
    _ = abs(_norm(v_rocket_final) - _norm(v_earth_final))  # informational only

    result = {
        "case": label,
        "t0_mjd": t0_mjd,
        "rp_design_AU": rp_design,
        "rp_actual_AU": round(km_to_au(traj.r_p_achieved_km), 6),
        "flight_time_days": round(traj.t_total_days, 2),
        "departure": {
            "r_earth_helio_km": _fmt(r_earth0),
            "v_earth_helio_kms": _fmt(v_earth0),
            "v_rocket_helio_kms": _fmt(v_rocket_pre),
            "v_rel_depart_norm_kms": round(traj.v_inf_earth, 4),
            "earth_speed_kms": round(earth_dep_speed, 4),
            "rocket_speed_kms": round(_norm(v_rocket_pre), 4),
        },
        "moon": {
            "v_moon_helio_kms": _fmt(v_moon),
            "v_rocket_pre_kms": _fmt(v_rocket_pre),
            "v_rocket_post_kms": _fmt(v_rocket_post),
            "v_inf_in_norm_kms": round(_norm(v_inf_in), 4),
            "v_inf_out_norm_kms": round(_norm(v_inf_out), 4),
            "turn_angle_deg": round(traj.swingby.delta_deg, 4) if traj.swingby else None,
            "dv_moon_kms": round(traj.swingby.dv_mag if traj.swingby else 0, 6),
        },
        "return": {
            "r_earth_helio_km": _fmt(r_earth_final),
            "v_earth_helio_kms": _fmt(v_earth_final),
            "v_rocket_helio_kms": _fmt(v_rocket_final),
            "v_rel_return_vec_kms": _fmt(v_rel_return_vec),
            "v_rel_return_norm_kms": round(v_rel_return_norm, 4),
            "scalar_speed_difference_kms": round(scalar_diff, 4),
            "angle_rocket_earth_deg": round(return_angle, 2),
            "dv_reentry_formula": "max(0, v_rel_return_norm - 15)",
            "dv_reentry_kms": round(dv_reentry, 4),
        },
        "dv_components": {
            "dv_launch_kms": round(traj.v_launch, 4),
            "dv_lunar_residual_kms": round(traj.swingby.dv_mag if traj.swingby else 0, 6),
            "dv_reentry_kms": round(dv_reentry, 4),
            "dv_total_kms": round(traj.v_launch + (traj.swingby.dv_mag if traj.swingby else 0) + dv_reentry, 4),
        },
        "warnings": warnings,
    }
    return result


def audit_no_lunar_nbody(t0_mjd, body_data, rp_design=0.3):
    """No-lunar baseline using full N-body: solve_trajectory then skip swingby effect."""
    params = DesignParams(t0_mjd=t0_mjd, r_m=R_MOON+500, side="trailing", r_p=rp_design*AU_KM)
    traj = solve_trajectory(params, body_data, verbose=False)

    # The no-lunar case uses the same pre-swingby state, then continues WITHOUT swingby Δv
    v_no_lunar = traj.v_at_moon.copy()
    # Continue propagation from pre-swingby state (same as if swingby didn't happen)
    # This is a proxy — a true no-lunar would need a different solve_trajectory path

    r_earth0, v_earth0 = traj.r_earth_t0, traj.v_earth_t0
    v_rel_return_norm = 0
    dv_reentry = 0

    return {
        "case": "no_lunar_nbody_proxy",
        "t0_mjd": t0_mjd,
        "rp_design_AU": rp_design,
        "rp_actual_AU": None,
        "flight_time_days": None,
        "departure": {
            "r_earth_helio_km": _fmt(r_earth0),
            "v_earth_helio_kms": _fmt(v_earth0),
            "v_rel_depart_norm_kms": round(traj.v_inf_earth, 4),
            "earth_speed_kms": round(_norm(v_earth0), 4),
        },
        "return": None,
        "dv_components": None,
        "warnings": ["N-body no-lunar baseline requires a separate solve_trajectory path without swingby. This proxy is incomplete."],
    }


def audit_baseline_fairness(lunar, no_lunar):
    reasons = []
    if lunar["t0_mjd"] != no_lunar["t0_mjd"]:
        reasons.append(f"t0 differs: {lunar['t0_mjd']} vs {no_lunar['t0_mjd']}")
    if abs(lunar["rp_design_AU"] - no_lunar["rp_design_AU"]) > 1e-6:
        reasons.append(f"rp_design differs: {lunar['rp_design_AU']} vs {no_lunar['rp_design_AU']}")
    if no_lunar.get("return") is None:
        reasons.append("No-lunar has no return leg computed (N-body propagation needed)")
    warnings = lunar.get("warnings", []) + no_lunar.get("warnings", [])
    return len(reasons) == 0, reasons, warnings


def main():
    bd = fetch_sem_vectors(use_cache=True)
    t0_a, t0_c = 61066.0, 61154.0

    # Case A: M5 lunar
    a = audit_lunar_case(t0_a, "M5_nominal_lunar", bd)

    # Case B: no-lunar (N-body proxy — limited)
    b = audit_no_lunar_nbody(t0_a, bd)

    # Case C: M6 best_by_dv
    c = audit_lunar_case(t0_c, "M6_best_by_dv", bd)

    # Case D: M6 best_balanced for comparison
    d = audit_lunar_case(t0_a, "M6_best_balanced_proxy", bd)

    cases = [a, b, c, d]

    # Fairness
    cmp_valid, cmp_reasons, all_warnings = audit_baseline_fairness(a, b)

    # Collect all return angles for lunar cases
    for case in [a, c, d]:
        ret = case.get("return")
        if ret:
            angle = ret["angle_rocket_earth_deg"]
            if angle > 150:
                all_warnings.append(f"{case['case']}: return angle={angle:.1f}° — rocket nearly opposite Earth direction")

    output = {
        "audit_cases": cases,
        "comparison_valid": cmp_valid,
        "comparison_reasons": cmp_reasons,
        "note": (
            "M5 no-lunar baseline currently uses symmetric patched-conic approximation. "
            "Lunar case uses full N-body. Direct comparison invalid. "
            "A proper N-body no-lunar baseline requires a new solve_trajectory path without swingby."
        ),
        "all_warnings": all_warnings,
        "has_bugs": bool(all_warnings),
        "bug_summary": all_warnings if all_warnings else ["None detected"],
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    json_path = out_dir / "m5_m6_dv_audit.json"
    with open(json_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[Audit] -> {json_path}")

    print(f"\n{'='*66}")
    print("M5/M6 DV Audit")
    print(f"{'='*66}")
    for case in cases:
        dc = case["dv_components"]
        ret = case.get("return")
        print(f"\n  {case['case']} (MJD {case['t0_mjd']:.0f}):")
        print(f"    rp={case['rp_actual_AU']} AU, flight={case['flight_time_days']} d")
        if ret:
            print(f"    v_rel_return={ret['v_rel_return_norm_kms']:.2f} km/s, "
                  f"angle={ret['angle_rocket_earth_deg']:.1f}°, "
                  f"dv_reentry={ret['dv_reentry_kms']:.1f}")
        if dc:
            print(f"    dv_launch={dc['dv_launch_kms']:.2f}, dv_moon={dc['dv_lunar_residual_kms']:.4f}, "
                  f"dv_reentry={dc['dv_reentry_kms']:.1f}, total={dc['dv_total_kms']:.1f}")
        for w in case["warnings"]:
            print(f"    WARNING: {w}")

    print(f"\n  Comparison valid: {cmp_valid}")
    for r in cmp_reasons:
        print(f"    {r}")
    print(f"  Warnings: {all_warnings if all_warnings else 'None'}")
    print(f"  Bugs: {'YES' if all_warnings else 'NO'}")


if __name__ == "__main__":
    main()
