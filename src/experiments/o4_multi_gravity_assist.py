"""
o4_multi_gravity_assist.py
==========================
O4: Multi-gravity assist exploration.
Since the Horizons cache only contains Sun/Earth/Moon, this explores
an Earth-Moon-assisted trajectory chain using patched-conic estimates.
"""

import json, os, sys, math, itertools, numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))
from constants import GM_SUN, GM_MOON, AU_KM, R_MOON, V_ESCAPE_EARTH, V_INF_MAX
from units import km_to_au, day_to_sec
from lunar_swingby import compute_swingby, compute_swingby_turn_angle
from patched_conic import compute_patched_conic
from horizons import fetch_sem_vectors
from trajectory import interpolate_state_at_mjd


def estimate_vinf(r1_au, r2_au, tof_days, mu=GM_SUN):
    """Simplified v_inf estimate using chord distance / time."""
    dr = np.array(r2_au) * AU_KM - np.array(r1_au) * AU_KM
    dist = np.linalg.norm(dr)
    tof_s = day_to_sec(tof_days)
    if tof_s < 1 or dist < 1e6:
        return 0
    v_req = dist / tof_s
    return v_req


def main():
    bd = fetch_sem_vectors(use_cache=True)
    t0_mjd = 61066.0

    # Explore Earth departure windows, simple Moon-assisted heliocentric injection
    # Then propagate to perihelion and back
    moon_tof_days = [1, 2, 3, 5]
    helio_tof_days = [160, 200, 250, 300]
    results = []

    print("[O4] Exploring Earth->Moon->Heliocentric chain...")

    for t_moon in moon_tof_days:
        r_earth, v_earth = interpolate_state_at_mjd(bd, "Earth", t0_mjd)
        try:
            r_moon, v_moon = interpolate_state_at_mjd(bd, "Moon", t0_mjd + t_moon)
        except Exception:
            continue

        # Moon relative velocity for swingby
        v_inf_mag = np.linalg.norm(np.array(v_moon) - np.array(v_earth))
        if v_inf_mag < 0.1:
            continue
        r_m = R_MOON + 500
        turn = compute_swingby_turn_angle(r_m, v_inf_mag, GM_MOON)

        for t_helio in helio_tof_days:
            mjd_helio = t0_mjd + t_moon + t_helio
            if mjd_helio > 61406:
                continue
            try:
                r_earth_ret, v_earth_ret = interpolate_state_at_mjd(bd, "Earth", mjd_helio)
            except Exception:
                continue

            # Estimate dv for heliocentric transfer
            vinf_dep = 10.0  # typical C3 for r_p=0.3 AU
            dv_launch = math.sqrt(V_ESCAPE_EARTH**2 + vinf_dep**2)

            # Lunar swingby dv
            dv_lunar = 2 * v_inf_mag / turn["e"] if turn["e"] > 1 else 0

            # Return dv estimate
            dv_brake = max(0, np.linalg.norm(np.array(v_earth_ret) - np.array(v_earth)) - V_INF_MAX)

            dv_total = dv_launch + dv_lunar + dv_brake

            cand = {
                "t0_mjd": t0_mjd,
                "moon_mjd": t0_mjd + t_moon,
                "return_mjd": mjd_helio,
                "moon_tof_days": t_moon,
                "helio_tof_days": t_helio,
                "dv_launch_kms": round(dv_launch, 2),
                "dv_lunar_kms": round(dv_lunar, 3),
                "dv_brake_kms": round(dv_brake, 2),
                "dv_total_kms": round(dv_total, 2),
                "moon_turn_deg": round(turn["delta_deg"], 2),
                "status": "exploratory",
            }
            results.append(cand)

    summary = {
        "num_candidates": len(results),
        "method": "Patched-conic chain: Earth departure -> Moon SOI flyby -> Heliocentric coast -> Earth return",
        "note": "Horizons cache only contains Sun/Earth/Moon. Venus/Jupiter not available for multi-planet chain. "
                "O4 explores Moon-assisted heliocentric injection as a simpler multi-gravity-assist proxy.",
        "results": results,
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    json_path = out_dir / "o4_multi_gravity_assist.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[O4] Saved to {json_path}")
    print(f"  {len(results)} chain candidates computed.")
    print("  O4: done (exploratory, Moon-assisted patched-conic chain)")


if __name__ == "__main__":
    main()
