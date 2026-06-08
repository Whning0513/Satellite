"""
m5_no_lunar_comparison.py
=========================
M5: Compare lunar-assist trajectory vs direct patched-conic (no lunar flyby).
Output: data/results/m5_no_lunar_comparison.json, .csv
"""

import json, os, csv, sys, numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import GM_SUN, AU_KM, R_MOON, V_ESCAPE_EARTH, V_INF_MAX
from trajectory import DesignParams, solve_trajectory
from patched_conic import compute_patched_conic
from units import au_to_km, km_to_au
from horizons import fetch_sem_vectors
from trajectory import interpolate_state_at_mjd


def solve_direct_no_lunar(t0_mjd, rp_design_AU, body_data):
    """Direct patched-conic transfer without lunar assist.

    Steps:
    1. Get Earth heliocentric state at t0.
    2. Patched conic gives required v_inf for transfer orbit.
    3. C3 = v_inf^2, v_launch = sqrt(v_esc^2 + v_inf^2).
    4. Propagate patched-conic: flight is T/2 (half period).
    5. At return, compute v_rel_earth and braking dv.
    """
    r_earth, v_earth = interpolate_state_at_mjd(body_data, "Earth", t0_mjd)
    elements = compute_patched_conic(r_p_AU=rp_design_AU)
    v_inf_depart = abs(elements.delta_v)  # km/s
    v_launch = np.sqrt(V_ESCAPE_EARTH**2 + v_inf_depart**2)

    # Propagation: approximate as patched-conic half-period
    # Use simple Lambert-like: at return, Earth is at different position
    # For direct transfer, reentry v_inf ≈ |Δv| (coplanar return)
    v_inf_return = v_inf_depart  # same magnitude in patched conic approx
    v_reentry = np.sqrt(V_ESCAPE_EARTH**2 + v_inf_return**2)
    dv_reentry_brake = max(0, v_inf_return - V_INF_MAX)

    dv_total = v_launch + dv_reentry_brake
    flight_time_days = elements.dt_flight_days

    return {
        "mode": "direct_no_lunar",
        "t0_mjd": t0_mjd,
        "rp_design_AU": rp_design_AU,
        "rp_actual_AU": rp_design_AU,
        "rp_error_rel": 0.0,
        "dv_launch_kms": round(v_launch, 4),
        "dv_lunar_residual_kms": 0.0,
        "dv_reentry_brake_kms": round(dv_reentry_brake, 4),
        "dv_total_corrected_kms": round(dv_total, 4),
        "v_inf_depart_kms": round(v_inf_depart, 4),
        "v_inf_return_kms": round(v_inf_return, 4),
        "flight_time_days": round(flight_time_days, 2),
        "constraints_satisfied": bool(dv_reentry_brake < 30),
    }


def main():
    body_data = fetch_sem_vectors(use_cache=True)
    t0_mjd = 61066.0
    rp = 0.3

    # Lunar-assist case
    params = DesignParams(t0_mjd=t0_mjd, r_m=R_MOON+500, side="trailing", r_p=rp*AU_KM)
    traj = solve_trajectory(params, body_data, verbose=False)

    lunar = {
        "mode": "lunar_assist",
        "t0_mjd": t0_mjd,
        "r_m_km": params.r_m,
        "side": params.side,
        "rp_design_AU": rp,
        "rp_actual_AU": round(km_to_au(traj.r_p_achieved_km), 6),
        "rp_error_rel": round(abs(traj.r_p_achieved_km - rp*AU_KM) / (rp*AU_KM), 6),
        "dv_launch_kms": round(traj.v_launch, 4),
        "dv_lunar_residual_kms": round(traj.swingby.dv_mag, 4) if traj.swingby else 0.0,
        "dv_reentry_brake_kms": round(max(0, traj.v_rel_earth - V_INF_MAX), 4),
        "dv_total_corrected_kms": round(traj.v_launch + (traj.swingby.dv_mag if traj.swingby else 0) + max(0, traj.v_rel_earth - V_INF_MAX), 4),
        "v_inf_depart_kms": round(traj.v_inf_earth, 4),
        "v_inf_return_kms": round(traj.v_rel_earth, 4),
        "flight_time_days": round(traj.t_total_days, 2),
        "dist_moon_min_km": round(traj.dist_moon_min, 1),
        "constraints_satisfied": bool(traj.dist_moon_min < 66000),
    }

    # No-lunar case
    direct = solve_direct_no_lunar(t0_mjd, rp, body_data)

    # Savings
    launch_saving = (direct["dv_launch_kms"] - lunar["dv_launch_kms"]) / direct["dv_launch_kms"]
    total_saving = (direct["dv_total_corrected_kms"] - lunar["dv_total_corrected_kms"]) / direct["dv_total_corrected_kms"]

    results = [lunar, direct]
    summary = {
        "t0_mjd": t0_mjd,
        "launch_saving_ratio": round(launch_saving, 4),
        "total_saving_ratio": round(total_saving, 4),
        "note": "Positive saving = lunar assist reduces cost. dv_reentry_brake = max(0, v_inf_return - 15 km/s).",
        "results": results,
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    json_path = out_dir / "m5_no_lunar_comparison.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[M5] Saved to {json_path}")

    csv_path = out_dir / "m5_no_lunar_comparison.csv"
    with open(csv_path, "w", newline="") as f:
        fields = ["mode", "dv_launch_kms", "dv_lunar_residual_kms", "dv_reentry_brake_kms",
                  "dv_total_corrected_kms", "rp_actual_AU", "rp_error_rel",
                  "flight_time_days", "constraints_satisfied"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"[M5] Saved to {csv_path}")

    print(f"\n  Lunar-assist: dv_launch={lunar['dv_launch_kms']:.2f}, "
          f"dv_lunar={lunar['dv_lunar_residual_kms']:.3f}, "
          f"dv_brake={lunar['dv_reentry_brake_kms']:.1f}, "
          f"total={lunar['dv_total_corrected_kms']:.1f} km/s")
    print(f"  Direct:       dv_launch={direct['dv_launch_kms']:.2f}, "
          f"dv_lunar=0, dv_brake={direct['dv_reentry_brake_kms']:.1f}, "
          f"total={direct['dv_total_corrected_kms']:.1f} km/s")
    print(f"  Launch saving:  {launch_saving:.2%}")
    print(f"  Total saving:   {total_saving:.2%}")


if __name__ == "__main__":
    main()
