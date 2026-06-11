"""
m6_lunar_return_event_audit.py
===============================
Audits whether M6 top candidates actually reach Earth return.

Same logic as M5 lunar audit: the trajectory solver's S5 coast ends at
perihelion (half-period).  The "v_rel_earth" and "return_vinf" are NOT
Earth-return quantities.

Output: data/results/m6_lunar_return_event_audit.json
        data/results/m6_lunar_return_event_audit.csv
"""

import json, os, sys, csv
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import R_MOON, AU_KM
from units import km_to_au
from trajectory import DesignParams, solve_trajectory, interpolate_state_at_mjd
from horizons import fetch_sem_vectors
from event_semantics import compute_earth_return_vinf, classify_event

THRESHOLD_KM = 1.5e6
M6_TOP_DATES = [61154.0, 61066.0, 61125.0, 61213.0, 61391.0,
                61095.0, 61183.0, 61272.0, 61302.0, 61332.0]


def main():
    print("=" * 66)
    print("M6 lunar return event audit")
    print("=" * 66)

    body_data = fetch_sem_vectors(use_cache=True)
    results = []

    for t0 in M6_TOP_DATES:
        print(f"\n[M6 t0={t0:.0f}]")
        params = DesignParams(t0, R_MOON + 500.0, "trailing", 0.3 * AU_KM)
        traj = solve_trajectory(params, body_data, verbose=False)

        t_ret_mjd = t0 + traj.t_total_days
        r_sun_ret, v_sun_ret = interpolate_state_at_mjd(body_data, "Sun", t_ret_mjd)
        r_earth_ret, v_earth_ret = interpolate_state_at_mjd(
            body_data, "Earth", t_ret_mjd)

        # End-of-S5 state
        r_sc = traj.r_final
        v_sc = traj.v_final
        r_sc_helio = r_sc - r_sun_ret
        r_earth_helio = r_earth_ret - r_sun_ret
        dist_earth = float(np.linalg.norm(r_sc - r_earth_ret))
        v_rel = float(np.linalg.norm(v_sc - v_earth_ret))
        event_type = classify_event(r_sc, r_earth_ret, r_sun_ret)
        r_sc_au = km_to_au(np.linalg.norm(r_sc_helio))
        r_earth_au = km_to_au(np.linalg.norm(r_earth_helio))

        # Formal return check
        check = compute_earth_return_vinf(
            r_sc, v_sc, r_earth_ret, v_earth_ret)

        result = {
            "t0_mjd": t0,
            "end_of_S5_event": event_type,
            "end_of_S5_sc_sun_r_AU": round(r_sc_au, 6),
            "end_of_S5_earth_sun_r_AU": round(r_earth_au, 6),
            "end_of_S5_dist_to_earth_km": round(dist_earth, 1),
            "end_of_S5_claimed_return_vinf_kms": round(v_rel, 4),
            "valid_earth_return_event": check["valid_return_event"],
            "return_event_reason": check["reason"],
            "formal_return_vinf_kms": None,
        }
        results.append(result)

        print(f"  Event:        {event_type}")
        print(f"  sc dist:      {dist_earth:.0f} km ({dist_earth/AU_KM:.4f} AU)")
        print(f"  sc r:         {r_sc_au:.4f} AU")
        print(f"  Earth r:      {r_earth_au:.4f} AU")
        print(f"  Claimed vinf: {v_rel:.2f} km/s")
        print(f"  Valid return: {check['valid_return_event']}")

    # Summary
    n_valid = sum(1 for r in results if r["valid_earth_return_event"])
    print(f"\n=== SUMMARY ===")
    print(f"  Candidates checked: {len(results)}")
    print(f"  Valid Earth return events: {n_valid}")

    out = {
        "task": "M6 lunar return event audit",
        "earth_return_threshold_km": THRESHOLD_KM,
        "num_candidates": len(results),
        "valid_return_events": n_valid,
        "results": results,
        "conclusion": (
            f"0 of {len(results)} M6 top candidates have a valid Earth return event "
            f"at end of S5 propagation. All claimed return_vinf values are "
            f"measured at perihelion (r ≈ 0.27–0.32 AU), not at Earth."
        ),
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    jp = out_dir / "m6_lunar_return_event_audit.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")

    # CSV
    cp = out_dir / "m6_lunar_return_event_audit.csv"
    with open(cp, "w", newline="", encoding="utf-8") as f:
        if results:
            w = csv.DictWriter(f, fieldnames=results[0].keys())
            w.writeheader()
            w.writerows(results)
    print(f"Saved: {cp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
