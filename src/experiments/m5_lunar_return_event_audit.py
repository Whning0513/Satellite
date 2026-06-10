"""
m5_lunar_return_event_audit.py
================================
Audits whether the M5 lunar trajectory actually reaches Earth return.

The trajectory solver propagates the heliocentric coast for exactly a
half-period (dt_flight = T/2 ≈ 95.7 days).  At the end of this coast the
spacecraft is at perihelion (~0.28 AU), NOT at Earth (~1 AU).  The
"v_rel_earth" and "v_reentry" computed at this state are NOT Earth-return
quantities.

This script:
  1. Re-runs the nominal M5 lunar trajectory.
  2. Classifies the end-of-propagation event using event_semantics.
  3. If no Earth return is found, records that.
  4. Optionally continues the propagation past perihelion to search for
     actual Earth return (full second half of orbit).

Output: data/results/m5_lunar_return_event_audit.json
"""

import json, os, sys, time
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import GM_SUN, GM_EARTH, GM_MOON, AU_KM, R_MOON
from units import km_to_au, day_to_sec, sec_to_day
from trajectory import DesignParams, solve_trajectory, interpolate_state_at_mjd
from nbody import propagate_nbody
from horizons import fetch_sem_vectors
from event_semantics import compute_earth_return_vinf, classify_event

M5_T0 = 61066.0


def main():
    print("=" * 66)
    print("M5 lunar return event audit")
    print("=" * 66)

    body_data = fetch_sem_vectors(use_cache=True)

    # ── 1. Run standard trajectory ──
    print("\n[1] Running solve_trajectory (standard)...")
    params = DesignParams(M5_T0, R_MOON + 500.0, "trailing", 0.3 * AU_KM)
    traj = solve_trajectory(params, body_data, verbose=False)

    t_ret_mjd = M5_T0 + traj.t_total_days
    r_sun_ret, v_sun_ret = interpolate_state_at_mjd(body_data, "Sun", t_ret_mjd)
    r_earth_ret, v_earth_ret = interpolate_state_at_mjd(
        body_data, "Earth", t_ret_mjd)

    state_helio = {
        "r_sc_km": traj.r_final,
        "v_sc_kms": traj.v_final,
        "r_earth_km": traj.r_earth_final,
        "v_earth_kms": traj.v_earth_final,
        "r_sun_km": r_sun_ret,
        "t_mjd": t_ret_mjd,
    }

    # Classify event at end of S5
    event_type_end = classify_event(
        state_helio["r_sc_km"], state_helio["r_earth_km"], r_sun_ret)
    dist_earth_end = float(np.linalg.norm(
        state_helio["r_sc_km"] - state_helio["r_earth_km"]))
    v_rel_end = float(np.linalg.norm(
        state_helio["v_sc_kms"] - state_helio["v_earth_kms"]))

    print(f"  End-of-S5 event type:     {event_type_end}")
    print(f"  Distance to Earth:        {dist_earth_end:.0f} km "
          f"({dist_earth_end/AU_KM:.4f} AU)")
    print(f"  v_rel (heliocentric diff): {v_rel_end:.2f} km/s")
    print(f"  Sc helio r:               {km_to_au(np.linalg.norm(state_helio['r_sc_km'] - state_helio['r_sun_km'])):.4f} AU")
    print(f"  Earth helio r:            {km_to_au(np.linalg.norm(state_helio['r_earth_km'] - state_helio['r_sun_km'])):.4f} AU")

    # ── 2. Formal return check ──
    print("\n[2] Formal Earth-return check (event_semantics)...")
    result = compute_earth_return_vinf(
        state_helio["r_sc_km"], state_helio["v_sc_kms"],
        state_helio["r_earth_km"], state_helio["v_earth_kms"])
    print(f"  Valid return event:       {result['valid_return_event']}")
    print(f"  Reason:                  {result['reason']}")

    # ── 3. Try extended propagation (full orbit) ──
    print("\n[3] Extended propagation: coast full orbit (≈191 days total)...")
    t_extra_days = 2 * traj.elements.dt_flight_days - traj.t_total_days
    t_extra_days = max(t_extra_days, 0.0) + 30  # a bit extra past full period
    print(f"  Extra coast: {t_extra_days:.0f} days")

    # Build initial state for extended propagation (current S5 end state)
    r_moon_ret, v_moon_ret = interpolate_state_at_mjd(body_data, "Moon", t_ret_mjd)
    r4_ext = [state_helio["r_sun_km"].copy(),
              state_helio["r_earth_km"].copy(),
              r_moon_ret.copy(),
              state_helio["r_sc_km"].copy()]
    v4_ext = [v_sun_ret.copy(),
              state_helio["v_earth_kms"].copy(),
              v_moon_ret.copy(),
              state_helio["v_sc_kms"].copy()]
    gm4 = [GM_SUN, GM_EARTH, GM_MOON, 0.0]

    if t_extra_days > 0:
        r_ext = [ri.copy() for ri in r4_ext]
        v_ext = [vi.copy() for vi in v4_ext]
        best_earth_dist = np.inf
        best_day = 0
        best_r_sc = None
        best_v_sc = None
        best_r_earth = None
        best_v_earth = None

        n_days = max(int(np.ceil(t_extra_days)), 1)
        print(f"  Propagating {n_days} additional days...")
        for day in range(1, n_days + 1):
            r_ext, v_ext = propagate_nbody(
                r_ext, v_ext, 86400.0, gm4, n_bodies=4, dt_internal=3600.0)
            cur_mjd = t_ret_mjd + day
            # Update Earth and Moon from Horizons at each step
            try:
                r_e_now, v_e_now = interpolate_state_at_mjd(
                    body_data, "Earth", cur_mjd)
                r_ext[1] = r_e_now.copy()
                v_ext[1] = v_e_now.copy()
                r_m_now, v_m_now = interpolate_state_at_mjd(
                    body_data, "Moon", cur_mjd)
                r_ext[2] = r_m_now.copy()
                v_ext[2] = v_m_now.copy()
            except Exception:
                pass
            r_sc_now = r_ext[3]
            r_earth_now = r_ext[1]
            dist = float(np.linalg.norm(r_sc_now - r_earth_now))
            if dist < best_earth_dist:
                best_earth_dist = dist
                best_day = day
                best_r_sc = r_sc_now.copy()
                best_v_sc = v_ext[3].copy()
                best_r_earth = r_earth_now.copy()
                best_v_earth = v_ext[1].copy()

        n_days = max(int(np.ceil(t_extra_days)), 1)
        for day in range(1, n_days + 1):
            r_ext, v_ext = propagate_nbody(
                r_ext, v_ext, 86400.0, gm4, n_bodies=4, dt_internal=3600.0)
            # Update Earth state from Horizons
            cur_mjd = t_ret_mjd + day
            try:
                r_e, v_e = interpolate_state_at_mjd(
                    body_data, "Earth", cur_mjd)
            except Exception:
                r_e, v_e = r_ext[1], v_ext[1]
            # Spaceraf is rocket at index 3 (or index 2 for position only?)
            # Actually we put sc at index 3
            r_sc_now = r_ext[3]
            r_earth_now = r_ext[1]
            dist = float(np.linalg.norm(r_sc_now - r_earth_now))
            if dist < best_earth_dist:
                best_earth_dist = dist
                best_day = day
                closest_r_sc = r_sc_now.copy()
                closest_v_sc = v_ext[3].copy()
                # Get closest-point Earth state
                try:
                    r_e_best, v_e_best = interpolate_state_at_mjd(
                        body_data, "Earth", cur_mjd)
                except Exception:
                    r_e_best, v_e_best = r_ext[1], v_ext[1]
                closest_v_earth = v_e_best.copy()

        print(f"  Best Earth approach: {best_earth_dist:.0f} km "
              f"after {best_day} extra days")
        print(f"  Sc-Sun r at closest: {km_to_au(np.linalg.norm(closest_r_sc - r_sun_ret)):.4f} AU")

        extended_result = None
        if best_earth_dist <= 1.5e6:
            print(f"  EARTH RETURN FOUND in extended propagation!")
            extended_result = compute_earth_return_vinf(
                best_r_sc, best_v_sc,
                best_r_earth, best_v_earth)
            print(f"  return_vinf: {extended_result['return_vinf_kms']} km/s")
            print(f"  dist to Earth: {best_earth_dist:.0f} km")
        else:
            print(f"  No Earth return in extended propagation.")
            print(f"  Closest approach still {best_earth_dist:.0f} km from Earth.")
            extended_result = {
                "valid_return_event": False,
                "closest_approach_km": round(best_earth_dist, 1),
                "best_approach_day": best_day,
                "return_vinf_kms": None,
                "reentry_speed_kms": None,
                "reason": f"Even with extended propagation, closest Earth approach is {best_earth_dist:.0f} km",
            }
    else:
        print("  No extra propagation needed (or t_extra_days <= 0)")
        extended_result = {
            "valid_return_event": False,
            "closest_approach_km": dist_earth_end,
            "return_vinf_kms": None,
            "reason": "Lunar trajectory S5 ends at perihelion, not Earth",
        }

    # ── Output ──
    out = {
        "task": "M5 lunar return event audit",
        "trajectory_type": "lunar_assisted (solve_trajectory)",
        "t0_mjd": M5_T0,
        "end_of_S5": {
            "event_type": event_type_end,
            "distance_to_earth_km": round(dist_earth_end, 1),
            "distance_to_earth_AU": round(dist_earth_end / AU_KM, 6),
            "sc_sun_r_AU": round(km_to_au(np.linalg.norm(
                state_helio["r_sc_km"] - state_helio["r_sun_km"])), 6),
            "earth_sun_r_AU": round(km_to_au(np.linalg.norm(
                state_helio["r_earth_km"] - state_helio["r_sun_km"])), 6),
            "claimed_return_vinf_kms": round(v_rel_end, 4),
            "valid_earth_return_event": result["valid_return_event"],
        },
        "extended_propagation": extended_result,
        "valid_earth_return_event_found": bool(
            extended_result and extended_result.get("valid_return_event")),
        "formal_return_vinf_kms": (
            extended_result["return_vinf_kms"]
            if extended_result and extended_result.get("valid_return_event")
            else None),
        "status": (
            "return_event_found" if (extended_result and
                                      extended_result.get("valid_return_event"))
            else "return_event_missing"),
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    jp = out_dir / "m5_lunar_return_event_audit.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
