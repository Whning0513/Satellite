"""
m5_m6_dv_audit.py
=================
M5/M6 Δv consistency audit.
Re-computes trajectories for lunar/no-lunar/best-by-dv cases,
outputs full velocity vectors at each phase, flags suspicious values.

Output: data/results/m5_m6_dv_audit.json, .csv
"""

import json, os, sys, numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import GM_SUN, GM_EARTH, GM_MOON, AU_KM, R_MOON, V_ESCAPE_EARTH, V_INF_MAX, V_EARTH_ORBIT
from units import km_to_au
from trajectory import DesignParams, solve_trajectory, interpolate_state_at_mjd
from patched_conic import compute_patched_conic
from horizons import fetch_sem_vectors


def _v(v):
    """Ensure numpy array."""
    return np.array(v, dtype=float)


def _norm(v):
    return float(np.linalg.norm(_v(v)))


def _fmt(v):
    return [round(float(x), 4) for x in _v(v)]


def audit_lunar_case(t0_mjd, label, body_data, rp_design=0.3):
    """Full velocity audit for a lunar-assist case."""
    params = DesignParams(t0_mjd=t0_mjd, r_m=R_MOON+500, side="trailing", r_p=rp_design*AU_KM)
    traj = solve_trajectory(params, body_data, verbose=False)

    # Earth departure vectors
    r_earth0 = traj.r_earth_t0
    v_earth0 = traj.v_earth_t0
    v_rocket_depart = traj.v_at_moon  # pre-swingby rocket velocity near Moon
    v_inf_earth = traj.v_inf_earth

    # Moon swingby vectors
    v_moon = traj.v_moon_t0
    v_rocket_pre = traj.v_at_moon
    v_rocket_post = traj.v_post_swingby
    v_inf_in = _v(v_rocket_pre) - _v(v_moon)
    v_inf_out = _v(v_rocket_post) - _v(v_moon)

    # Earth return vectors
    r_earth_final = traj.r_earth_final
    v_earth_final = traj.v_earth_final
    r_rocket_final = traj.r_final
    v_rocket_final = traj.v_final
    v_rel_return_vec = _v(v_rocket_final) - _v(v_earth_final)
    v_rel_return_norm = _norm(v_rel_return_vec)
    dv_reentry = max(0, v_rel_return_norm - V_INF_MAX)

    # Check: helicentric speeds
    v_earth_depart_norm = _norm(v_earth0)
    v_earth_return_norm = _norm(v_earth_final)
    v_rocket_depart_norm = _norm(v_rocket_depart)
    v_rocket_return_norm = _norm(v_rocket_final)

    warnings = []
    if v_earth_depart_norm < 10 or v_earth_depart_norm > 50:
        warnings.append(f"v_earth_depart_norm={v_earth_depart_norm:.1f} km/s (expected ~29.8)")
    if v_rel_return_norm > 100:
        warnings.append(f"v_rel_return={v_rel_return_norm:.1f} km/s > 100 — possible unit/frame bug")

    result = {
        "case": label,
        "t0_mjd": t0_mjd,
        "rp_design_AU": rp_design,
        "rp_actual_AU": round(km_to_au(traj.r_p_achieved_km), 6),
        "success": traj.success,
        "earth_departure": {
            "r_earth_helio_km": _fmt(r_earth0),
            "v_earth_helio_kms": _fmt(v_earth0),
            "v_earth_speed_kms": round(v_earth_depart_norm, 4),
        },
        "moon_swingby": {
            "v_moon_helio_kms": _fmt(v_moon),
            "v_rocket_pre_kms": _fmt(v_rocket_pre),
            "v_rocket_post_kms": _fmt(v_rocket_post),
            "v_inf_in_norm_kms": round(_norm(v_inf_in), 4),
            "v_inf_out_norm_kms": round(_norm(v_inf_out), 4),
            "turn_angle_deg": round(traj.swingby.delta_deg, 4) if traj.swingby else None,
            "dv_moon_kms": round(traj.swingby.dv_mag, 6) if traj.swingby else 0,
        },
        "earth_return": {
            "r_earth_return_helio_km": _fmt(r_earth_final),
            "v_earth_return_helio_kms": _fmt(v_earth_final),
            "v_earth_return_speed_kms": round(v_earth_return_norm, 4),
            "v_rocket_return_helio_kms": _fmt(v_rocket_final),
            "v_rocket_return_speed_kms": round(v_rocket_return_norm, 4),
            "v_rel_return_vec_kms": _fmt(v_rel_return_vec),
            "v_rel_return_norm_kms": round(v_rel_return_norm, 4),
            "dv_reentry_brake_kms": round(dv_reentry, 4),
        },
        "dv_components": {
            "dv_launch_kms": round(traj.v_launch, 4),
            "dv_lunar_residual_kms": round(traj.swingby.dv_mag, 6) if traj.swingby else 0,
            "dv_reentry_brake_kms": round(dv_reentry, 4),
            "dv_total_corrected_kms": round(traj.v_launch + (traj.swingby.dv_mag if traj.swingby else 0) + dv_reentry, 4),
        },
        "unit_checks": {
            "expected_earth_orbital_speed_kms": V_EARTH_ORBIT,
            "measured_earth_depart_speed_kms": round(v_earth_depart_norm, 4),
            "measured_earth_return_speed_kms": round(v_earth_return_norm, 4),
            "rocket_depart_speed_kms": round(v_rocket_depart_norm, 4),
            "rocket_return_speed_kms": round(v_rocket_return_norm, 4),
        },
        "warnings": warnings,
    }
    return result


def audit_no_lunar_case(t0_mjd, body_data, rp_design=0.3):
    """Audit for no-lunar direct patched-conic baseline."""
    r_earth0, v_earth0 = interpolate_state_at_mjd(body_data, "Earth", t0_mjd)
    elements = compute_patched_conic(r_p_AU=rp_design)

    # Departure
    v_inf_depart = abs(elements.delta_v)
    v_launch = float(np.sqrt(V_ESCAPE_EARTH**2 + v_inf_depart**2))

    # Departure velocity vector (retrograde for interior transfer)
    v_earth_dir = _v(v_earth0) / (_norm(v_earth0) + 1e-15)
    v_rocket_depart = _v(v_earth0) + v_inf_depart * (-v_earth_dir)

    # Return: propagate Earth to return time
    n_days = int(elements.dt_flight_days)
    mjd_return = t0_mjd + n_days + 5  # approximate, use patched-conic half period
    try:
        r_earth_ret, v_earth_ret = interpolate_state_at_mjd(body_data, "Earth", mjd_return)
    except Exception:
        # Fallback: same position (not accurate)
        r_earth_ret, v_earth_ret = r_earth0, -v_earth0

    # Return: same |Δv| as departure (patched-conic approximation)
    v_rel_return_norm = v_inf_depart
    v_rel_return_vec = -v_earth_dir * v_rel_return_norm

    dv_reentry = max(0, v_rel_return_norm - V_INF_MAX)
    dv_total = v_launch + dv_reentry

    # Speeds
    v_earth0_norm = _norm(v_earth0)
    v_rocket_depart_norm = _norm(v_rocket_depart)
    v_rocket_return_norm = v_rel_return_norm + v_earth0_norm  # approximate

    warnings = []
    if v_earth0_norm < 10 or v_earth0_norm > 50:
        warnings.append(f"v_earth={v_earth0_norm:.1f} km/s abnormal")
    if dv_total < 5:
        warnings.append(f"dv_total={dv_total:.1f} km/s suspiciously low")

    return {
        "case": "no_lunar_direct",
        "t0_mjd": t0_mjd,
        "rp_design_AU": rp_design,
        "rp_actual_AU": rp_design,
        "success": True,
        "earth_departure": {
            "r_earth_helio_km": _fmt(r_earth0),
            "v_earth_helio_kms": _fmt(v_earth0),
            "v_earth_speed_kms": round(v_earth0_norm, 4),
        },
        "moon_swingby": None,
        "earth_return": {
            "r_earth_return_helio_km": _fmt(r_earth_ret),
            "v_earth_return_helio_kms": _fmt(v_earth_ret),
            "v_rel_return_vec_kms": _fmt(v_rel_return_vec),
            "v_rel_return_norm_kms": round(v_rel_return_norm, 4),
            "dv_reentry_brake_kms": round(dv_reentry, 4),
        },
        "dv_components": {
            "dv_launch_kms": round(v_launch, 4),
            "dv_lunar_residual_kms": 0.0,
            "dv_reentry_brake_kms": round(dv_reentry, 4),
            "dv_total_corrected_kms": round(dv_total, 4),
        },
        "unit_checks": {
            "expected_earth_orbital_speed_kms": V_EARTH_ORBIT,
            "measured_earth_depart_speed_kms": round(v_earth0_norm, 4),
        },
        "warnings": warnings,
    }


def main():
    bd = fetch_sem_vectors(use_cache=True)
    t0_lunar = 61066.0
    t0_best = 61154.0

    cases = [
        audit_lunar_case(t0_lunar, "M5_nominal_lunar", bd),
        audit_no_lunar_case(t0_lunar, bd),
        audit_lunar_case(t0_best, "M6_best_by_dv", bd),
    ]

    # Comparison validity check
    lunar = cases[0]
    no_lunar = cases[1]

    comparison_valid = False
    comparison_reason = [
        "METHOD MISMATCH: Lunar case uses full 4-body N-body propagation (trajectory.solve_trajectory).",
        "No-lunar case uses symmetric patched-conic approximation (no N-body return propagation).",
        f"Lunar return v_rel={lunar['earth_return']['v_rel_return_norm_kms']:.1f} km/s (N-body).",
        f"No-lunar return v_rel={no_lunar['earth_return']['v_rel_return_norm_kms']:.1f} km/s (patched-conic symmetry).",
        "A fair comparison requires both to use the same propagation method for the return leg.",
        "Saving ratio not computed because comparison is invalid.",
        f"Lunar rp_actual={lunar['rp_actual_AU']:.4f} AU != no_lunar rp={no_lunar['rp_actual_AU']:.4f} AU (also incomparable).",
    ]
    lunar_dv = lunar["dv_components"]["dv_total_corrected_kms"]
    no_lunar_dv = no_lunar["dv_components"]["dv_total_corrected_kms"]
    saving = None
    saving_note = "Not computed — comparison is invalid (different propagation methods)"

    # All warnings
    all_warnings = []
    for c in cases:
        all_warnings.extend(c.get("warnings", []))

    # Unit checks
    for c in cases:
        v_earth = c["unit_checks"].get("measured_earth_depart_speed_kms", 0)
        if v_earth < 25 or v_earth > 35:
            all_warnings.append(f"{c['case']}: Earth speed {v_earth:.1f} km/s (expected ~29.8)")

    output = {
        "audit_cases": cases,
        "comparison_valid": bool(comparison_valid),
        "comparison_reason": comparison_reason,
        "lunar_vs_no_lunar": {
            "lunar_dv_total_corrected_kms": round(lunar_dv, 4),
            "no_lunar_dv_total_corrected_kms": round(no_lunar_dv, 4),
            "saving_ratio": saving,
            "note": saving_note,
        },
        "all_warnings": all_warnings,
        "has_bugs": bool(all_warnings),
        "bug_summary": all_warnings if all_warnings else ["None detected at vector level"],
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    json_path = out_dir / "m5_m6_dv_audit.json"
    with open(json_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[Audit] Saved to {json_path}")

    # Print summary
    print(f"\n{'='*66}")
    print("M5/M6 DV Consistency Audit")
    print(f"{'='*66}")
    for c in cases:
        dc = c["dv_components"]
        ret = c["earth_return"]
        print(f"\n  {c['case']} (MJD {c['t0_mjd']:.0f}):")
        print(f"    rp={c['rp_actual_AU']:.4f} AU")
        print(f"    v_earth_depart={c['unit_checks']['measured_earth_depart_speed_kms']:.2f} km/s")
        if c.get("moon_swingby"):
            ms = c["moon_swingby"]
            print(f"    v_inf_in={ms['v_inf_in_norm_kms']:.3f}, v_inf_out={ms['v_inf_out_norm_kms']:.3f}, turn={ms['turn_angle_deg']:.2f}°")
        print(f"    v_rel_return={ret['v_rel_return_norm_kms']:.2f} km/s")
        print(f"    dv_launch={dc['dv_launch_kms']:.2f}, dv_moon={dc['dv_lunar_residual_kms']:.3f}, dv_brake={dc['dv_reentry_brake_kms']:.2f}, total={dc['dv_total_corrected_kms']:.2f}")
        if c["warnings"]:
            for w in c["warnings"]:
                print(f"    WARNING: {w}")

    print(f"\n  Comparison valid: {comparison_valid}")
    for r in comparison_reason:
        print(f"    - {r}")
    print(f"  Lunar total: {lunar_dv:.2f} km/s")
    print(f"  No-lunar total: {no_lunar_dv:.2f} km/s")
    print(f"  Saving ratio: {saving}")
    print(f"  Saving note: {saving_note}")
    print(f"  Warnings: {all_warnings if all_warnings else 'None'}")
    print(f"\n  {'BUGS DETECTED' if all_warnings else 'No unit/frame bugs detected'}")


if __name__ == "__main__":
    main()
