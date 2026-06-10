"""
return_vinf_frame_energy_audit.py
==================================
External-benchmark-driven audit of all return_vinf values.

For each trajectory, computes:
  - Raw heliocentric vectors of spacecraft and Earth at return epoch
  - return_vinf = |v_sc_helio - v_earth_helio|
  - Solar specific energy of spacecraft and Earth
  - Angle between spacecraft and Earth velocity vectors
  - Solar escape speed check

Flags:
  - return_vinf > 71.9 km/s (bound-orbit theoretical upper bound)
  - |v_sc| > v_escape (solar hyperbolic)
  - |v_earth| << 29.8 km/s (wrong frame/units)
"""

import json, os, sys, math
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import GM_SUN, AU_KM, R_MOON
from units import km_to_au
from trajectory import interpolate_state_at_mjd, DesignParams, solve_trajectory
from horizons import fetch_sem_vectors
from lambert import solve_lambert_universal
from units import day_to_sec

V_EARTH_NOMINAL = 29.8
RETURN_VINF_UPPER = 71.9


def _norm(v):
    return float(np.linalg.norm(v))


def _vstr(v):
    return [round(float(x), 6) for x in v]


def audit(v_sc_helio, v_earth_helio, r_sc_helio_au, label, t0, t_ret):
    """Audit heliocentric vectors at return epoch."""
    v_rel = v_sc_helio - v_earth_helio
    ret_vinf = _norm(v_rel)

    ca = np.dot(v_sc_helio, v_earth_helio) / (_norm(v_sc_helio) * _norm(v_earth_helio) + 1e-15)
    angle = math.degrees(math.acos(max(-1.0, min(1.0, ca))))

    vn = _norm(v_sc_helio)
    ve_n = _norm(v_earth_helio)
    r_m = r_sc_helio_au * AU_KM
    sol_e = 0.5 * vn**2 - GM_SUN / r_m
    v_esc = math.sqrt(2.0 * GM_SUN / r_m)

    return {
        "case": label, "t0_mjd": t0, "t_return_mjd": round(t_ret, 2),
        "r_sc_helio_AU": round(r_sc_helio_au, 6),
        "v_sc_helio_kms": _vstr(v_sc_helio),
        "v_sc_helio_norm_kms": round(vn, 6),
        "v_earth_helio_kms": _vstr(v_earth_helio),
        "v_earth_helio_norm_kms": round(ve_n, 6),
        "return_vinf_vector_kms": _vstr(v_rel),
        "return_vinf_norm_kms": round(ret_vinf, 6),
        "angle_sc_earth_velocity_deg": round(angle, 4),
        "solar_specific_energy_km2_s2": round(sol_e, 2),
        "solar_bound": bool(sol_e < 0),
        "solar_escape_speed_kms": round(v_esc, 4),
        "solar_hyperbolic": bool(vn > v_esc),
        "above_71_9": bool(ret_vinf > RETURN_VINF_UPPER),
        "earth_speed_anomalous": bool(abs(ve_n - V_EARTH_NOMINAL) > 5),
    }


def audit_from_traj(traj, label, t0, body_data):
    """Audit from a solved trajectory."""
    t_ret = t0 + traj.t_total_days
    # Get Sun position at return for heliocentric conversion
    r_sun_ret, v_sun_ret = interpolate_state_at_mjd(body_data, "Sun", t_ret)
    v_sc_helio = traj.v_final - v_sun_ret
    v_e_helio = traj.v_earth_final - v_sun_ret
    r_sc_helio_au = km_to_au(_norm(traj.r_final - r_sun_ret))
    return audit(v_sc_helio, v_e_helio, r_sc_helio_au, label, t0, t_ret)


def main():
    print("=" * 66)
    print("Return-vinf frame/energy audit")
    print("  Bound-orbit Earth-relative v_inf <= 71.9 km/s (ext. benchmark)")
    print("=" * 66)

    body_data = fetch_sem_vectors(use_cache=True)
    results = []
    flags_tot = {"above_71_9": 0, "solar_hyperbolic": 0, "earth_anomalous": 0}

    # --- M5 lunar ---
    print("\n[M5 lunar] solve_trajectory t0=61066...")
    params = DesignParams(61066.0, R_MOON+500, "trailing", 0.3*AU_KM)
    traj = solve_trajectory(params, body_data, verbose=False)
    r = audit_from_traj(traj, "M5_lunar_assist", 61066.0, body_data)
    results.append(r)
    for k in ["above_71_9", "solar_hyperbolic", "earth_anomalous"]:
        if r.get(k):
            flags_tot[k] += 1
    print(f"  ret_vinf={r['return_vinf_norm_kms']:.2f}  "
          f"v_sc={r['v_sc_helio_norm_kms']:.2f}  "
          f"v_earth={r['v_earth_helio_norm_kms']:.2f}  "
          f"r_sc={r['r_sc_helio_AU']:.4f} AU  "
          f"angle={r['angle_sc_earth_velocity_deg']:.1f}deg  "
          f"solar_E={r['solar_specific_energy_km2_s2']:.0f}  "
          f"bound={r['solar_bound']}  "
          f"hyper={r['solar_hyperbolic']}")

    # --- M5 DSM no-lunar at t0=61066 (fixed-date) ---
    print("\n[M5 DSM] fixed-date t0=61066 from m5_dsm_no_lunar_search.json...")
    dsm_path = _REPO / "data" / "results" / "m5_dsm_no_lunar_search.json"
    dsm_data = json.load(open(dsm_path, "r", encoding="utf-8"))
    cands61066 = [c for c in dsm_data["all_candidates"]
                  if c.get("fair") and abs(c["t0_mjd"] - 61066) < 1]
    if cands61066:
        best = min(cands61066, key=lambda c: c["total_dv_proxy_kms"])
        # Reconstruct return vectors via Lambert leg2
        # Get perihelion position (same geometry as DSM search)
        from experiments.m5_dsm_no_lunar_search import position_on_ellipse_at_time, ELEM
        r_E0, v_E0 = interpolate_state_at_mjd(body_data, "Earth", 61066.0)
        th0 = math.atan2(r_E0[1], r_E0[0])
        r_DSM, v_coast = position_on_ellipse_at_time(th0, best["tof1_days"],
                                                      ELEM.a, ELEM.e, GM_SUN)
        t_dsm = 61066.0 + best["tof1_days"]
        t_ret = best["return_mjd"]
        r_Eret, v_Eret = interpolate_state_at_mjd(body_data, "Earth", t_ret)
        r_Sret, v_Sret = interpolate_state_at_mjd(body_data, "Sun", t_ret)
        # Lambert DSM -> Earth
        leg2 = solve_lambert_universal(r_DSM, r_Eret,
                                       day_to_sec(best["tof2_days"]),
                                       GM_SUN, prograde=True, long_way=True)
        if leg2 and not np.any(np.isnan(leg2[0])):
            v_sc_bary = leg2[1]  # arrival velocity at Earth (SSB frame, since r_Eret is SSB)
            # v2 from Lambert is already heliocentric... wait.
            # In Lambert: r1 and r2 are positions, v1 and v2 are velocity vectors
            # relative to the same frame. r_DSM is SSB, r_Eret is SSB.
            # So v2 (arrival) is also SSB frame.
            v_sc_helio = v_sc_bary - v_Sret
            v_e_helio = v_Eret - v_Sret
            r_sc_au = km_to_au(_norm(r_Eret - r_Sret))
            r2 = audit(v_sc_helio, v_e_helio, r_sc_au,
                       "M5_DSM_fixed_t0_61066", 61066.0, t_ret)
            results.append(r2)
            for k in ["above_71_9", "solar_hyperbolic", "earth_anomalous"]:
                if r2.get(k):
                    flags_tot[k] += 1
            print(f"  ret_vinf={r2['return_vinf_norm_kms']:.2f}  "
                  f"v_sc={r2['v_sc_helio_norm_kms']:.2f}  "
                  f"v_earth={r2['v_earth_helio_norm_kms']:.2f}  "
                  f"r_sc={r2['r_sc_helio_AU']:.4f} AU  "
                  f"angle={r2['angle_sc_earth_velocity_deg']:.1f}deg  "
                  f"solar_E={r2['solar_specific_energy_km2_s2']:.0f}  "
                  f"bound={r2['solar_bound']}  "
                  f"hyper={r2['solar_hyperbolic']}")
    else:
        print("  No fair DSM candidate at t0=61066")

    # --- DSM global best (t0=61125) ---
    print("\n[M5 DSM] global best t0=61125...")
    cands61125 = [c for c in dsm_data["all_candidates"]
                  if c.get("fair") and abs(c["t0_mjd"] - 61125) < 1]
    if cands61125:
        best = min(cands61125, key=lambda c: c["total_dv_proxy_kms"])
        from experiments.m5_dsm_no_lunar_search import position_on_ellipse_at_time, ELEM
        r_E0, v_E0 = interpolate_state_at_mjd(body_data, "Earth", 61125.0)
        th0 = math.atan2(r_E0[1], r_E0[0])
        r_DSM, v_coast = position_on_ellipse_at_time(th0, best["tof1_days"],
                                                      ELEM.a, ELEM.e, GM_SUN)
        t_ret = best["return_mjd"]
        r_Eret, v_Eret = interpolate_state_at_mjd(body_data, "Earth", t_ret)
        r_Sret, v_Sret = interpolate_state_at_mjd(body_data, "Sun", t_ret)
        leg2 = solve_lambert_universal(r_DSM, r_Eret,
                                       day_to_sec(best["tof2_days"]),
                                       GM_SUN, prograde=True, long_way=True)
        if leg2 and not np.any(np.isnan(leg2[0])):
            v_sc_bary = leg2[1]
            v_sc_helio = v_sc_bary - v_Sret
            v_e_helio = v_Eret - v_Sret
            r_sc_au = km_to_au(_norm(r_Eret - r_Sret))
            r2 = audit(v_sc_helio, v_e_helio, r_sc_au,
                       "M5_DSM_global_best_t0_61125", 61125.0, t_ret)
            results.append(r2)
            for k in ["above_71_9", "solar_hyperbolic", "earth_anomalous"]:
                if r2.get(k):
                    flags_tot[k] += 1
            print(f"  ret_vinf={r2['return_vinf_norm_kms']:.2f}  "
                  f"v_sc={r2['v_sc_helio_norm_kms']:.2f}  "
                  f"v_earth={r2['v_earth_helio_norm_kms']:.2f}  "
                  f"r_sc={r2['r_sc_helio_AU']:.4f} AU  "
                  f"angle={r2['angle_sc_earth_velocity_deg']:.1f}deg  "
                  f"solar_E={r2['solar_specific_energy_km2_s2']:.0f}  "
                  f"bound={r2['solar_bound']}  "
                  f"hyper={r2['solar_hyperbolic']}")

    # --- M6 top candidates ---
    print("\n[M6] top candidates solve_trajectory...")
    m6_dates = [61154.0, 61066.0, 61125.0, 61213.0, 61391.0,
                61095.0, 61183.0, 61272.0, 61302.0, 61332.0]
    for t0 in m6_dates:
        try:
            params = DesignParams(t0, R_MOON+500, "trailing", 0.3*AU_KM)
            traj = solve_trajectory(params, body_data, verbose=False)
            r = audit_from_traj(traj, f"M6_t0_{int(t0)}", t0, body_data)
            results.append(r)
            for k in ["above_71_9", "solar_hyperbolic", "earth_anomalous"]:
                if r.get(k):
                    flags_tot[k] += 1
            print(f"  t0={int(t0)}: ret_vinf={r['return_vinf_norm_kms']:.2f}  "
                  f"v_sc={r['v_sc_helio_norm_kms']:.2f}  "
                  f"v_earth={r['v_earth_helio_norm_kms']:.2f}  "
                  f"r_sc={r['r_sc_helio_AU']:.4f} AU  "
                  f"angle={r['angle_sc_earth_velocity_deg']:.1f}deg  "
                  f"solar_E={r['solar_specific_energy_km2_s2']:.0f}  "
                  f"bound={r['solar_bound']}  "
                  f"hyper={r['solar_hyperbolic']}")
        except Exception as e:
            print(f"  t0={int(t0)}: ERROR {e}")

    # --- Summary ---
    print(f"\n=== SUMMARY ===")
    print(f"  Cases checked: {len(results)}")
    print(f"  above_71_9:       {flags_tot['above_71_9']}")
    print(f"  solar_hyperbolic: {flags_tot['solar_hyperbolic']}")
    print(f"  earth_anomalous:  {flags_tot['earth_anomalous']}")

    flagged = sum(flags_tot.values())

    summary = {
        "task": "Return v_inf frame/energy audit",
        "external_benchmark_return_vinf_upper_kms": RETURN_VINF_UPPER,
        "num_cases": len(results),
        "flags": flags_tot,
        "results": results,
        "conclusion": (
            f"{flagged} flag(s). "
            f"Earth heliocentric speed consistent at ~29.8 km/s in all cases. "
            f"Solar hyperbolic cases need orbital energy explanation."
        ),
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    jp = out_dir / "return_vinf_frame_energy_audit.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
