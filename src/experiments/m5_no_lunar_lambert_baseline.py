"""
m5_no_lunar_lambert_baseline.py
================================
Search direct Earth-to-Earth Lambert transfer orbits from a fixed t0,
scanning return time tof_days, to find candidates that reach rp ≈ 0.3 AU
AND return to Earth.

Output: data/results/m5_no_lunar_lambert_baseline.json, .csv
"""

import json, os, csv, sys, math, itertools
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import GM_SUN, AU_KM, R_MOON, V_ESCAPE_EARTH, V_INF_MAX
from units import km_to_au
from trajectory import DesignParams, solve_trajectory, interpolate_state_at_mjd
from lambert import solve_lambert_universal, orbital_elements_from_state
from horizons import fetch_sem_vectors


def _norm(v):
    return float(np.linalg.norm(np.array(v, dtype=float)))


def _fmt(v):
    return [round(float(x), 4) for x in np.array(v, dtype=float)]


def launch_dv_from_vinf(vinf):
    return math.sqrt(V_ESCAPE_EARTH**2 + vinf**2)


def search_lambert_candidates(t0_mjd, body_data, tof_range=(100, 730, 5), rp_target=0.3):
    """Scan direct Earth-to-Earth Lambert transfers at fixed t0."""
    r_sun0, v_sun0 = interpolate_state_at_mjd(body_data, "Sun", t0_mjd)
    r_earth0, v_earth0 = interpolate_state_at_mjd(body_data, "Earth", t0_mjd)
    r0 = np.array(r_earth0) - np.array(r_sun0)
    vE0 = np.array(v_earth0) - np.array(v_sun0)

    mu = GM_SUN
    candidates = []

    tof_start, tof_end, step = tof_range

    for tof_days in range(tof_start, tof_end + 1, step):
        tf_mjd = t0_mjd + tof_days
        if tf_mjd > 62000:
            continue
        try:
            r_earth_f, v_earth_f = interpolate_state_at_mjd(body_data, "Earth", tf_mjd)
            r_sun_f, v_sun_f = interpolate_state_at_mjd(body_data, "Sun", tf_mjd)
        except Exception:
            continue

        rf = np.array(r_earth_f) - np.array(r_sun_f)
        vEf = np.array(v_earth_f) - np.array(v_sun_f)
        tof_s = tof_days * 86400.0

        for branch, prograde, long_way in [
            ("prograde_short", True, False),
            ("prograde_long", True, True),
            ("retrograde_short", False, False),
            ("retrograde_long", False, True),
        ]:
            try:
                v1, v2, diag = solve_lambert_universal(r0, rf, tof_s, mu, prograde=prograde, long_way=long_way)
            except Exception:
                continue

            if _norm(v1) > 1e6 or _norm(v2) > 1e6:
                continue

            # Orbital elements
            a, e, rp_km, eps, h = orbital_elements_from_state(r0, v1, mu)
            rp_AU = km_to_au(rp_km)
            period_days = 2 * math.pi * math.sqrt(abs(a)**3 / mu) / 86400 if a > 0 else 1e15

            # Earth departure
            v_inf_depart_vec = v1 - vE0
            v_inf_depart = _norm(v_inf_depart_vec)
            dv_launch = launch_dv_from_vinf(v_inf_depart)

            # Earth return
            v_inf_return_vec = v2 - vEf
            v_inf_return = _norm(v_inf_return_vec)
            dv_reentry = max(0, v_inf_return - V_INF_MAX)
            dv_total = dv_launch + dv_reentry

            rp_valid = abs(rp_AU - rp_target) / rp_target < 0.10
            reentry_valid = v_inf_return <= 15

            # Score: dv_total + penalties
            penalty_rp = 100 * max(0, abs(rp_AU - rp_target) / rp_target - 0.10)
            penalty_reentry = 10 * max(0, v_inf_return - 15)
            score = dv_total + penalty_rp + penalty_reentry

            candidates.append({
                "t0_mjd": t0_mjd,
                "tf_mjd": round(tf_mjd, 2),
                "tof_days": tof_days,
                "branch": branch,
                "prograde": prograde,
                "long_way": long_way,
                "a_AU": round(km_to_au(abs(a)), 6),
                "e": round(e, 6),
                "rp_AU": round(rp_AU, 6),
                "rp_target_AU": rp_target,
                "rp_error_rel": round(abs(rp_AU - rp_target) / rp_target, 6),
                "rp_valid": bool(rp_valid),
                "period_days": round(period_days, 1),
                "v_inf_depart_kms": round(v_inf_depart, 4),
                "v_inf_return_kms": round(v_inf_return, 4),
                "reentry_valid": bool(reentry_valid),
                "dv_launch_kms": round(dv_launch, 4),
                "dv_reentry_kms": round(dv_reentry, 4),
                "dv_total_kms": round(dv_total, 4),
                "score": round(score, 2),
                "constraints_satisfied": bool(rp_valid and reentry_valid and tof_days <= 730),
            })

    return candidates


def get_lunar_reference(t0_mjd, body_data, rp_design=0.3):
    """Lunar-assist reference."""
    params = DesignParams(t0_mjd=t0_mjd, r_m=R_MOON+500, side="trailing", r_p=rp_design*AU_KM)
    traj = solve_trajectory(params, body_data, verbose=False)
    v_rel_return = _norm(np.array(traj.v_final) - np.array(traj.v_earth_final))
    dv_brake = max(0, v_rel_return - V_INF_MAX)
    dv_moon = traj.swingby.dv_mag if traj.swingby else 0
    return {
        "t0_mjd": t0_mjd,
        "rp_actual_AU": round(km_to_au(traj.r_p_achieved_km), 6),
        "rp_error_rel": round(abs(traj.r_p_achieved_km - rp_design*AU_KM) / (rp_design*AU_KM), 6),
        "dv_launch_kms": round(traj.v_launch, 4),
        "dv_lunar_kms": round(dv_moon, 4),
        "v_rel_return_kms": round(v_rel_return, 4),
        "dv_reentry_kms": round(dv_brake, 4),
        "dv_total_kms": round(traj.v_launch + dv_moon + dv_brake, 4),
        "flight_time_days": round(traj.t_total_days, 2),
    }


def pick_best(candidates):
    if not candidates:
        return None, None, None
    best_rp = min(candidates, key=lambda c: abs(c["rp_AU"] - c["rp_target_AU"]))
    best_dv = min(candidates, key=lambda c: c["dv_total_kms"])
    feasible = [c for c in candidates if c["constraints_satisfied"]]
    best_feas = min(feasible, key=lambda c: c["score"]) if feasible else None
    return best_rp, best_dv, best_feas


def main():
    bd = fetch_sem_vectors(use_cache=True)
    t0s = [61066.0, 61154.0]

    results = []
    for t0 in t0s:
        print(f"\n{'='*55}")
        print(f"  t0 = MJD {t0:.0f}")
        print(f"{'='*55}")

        # Lunar reference
        lunar = get_lunar_reference(t0, bd)
        print(f"  Lunar reference: rp={lunar['rp_actual_AU']:.4f} AU, dv_total={lunar['dv_total_kms']:.1f} km/s")

        # Lambert search
        cands = search_lambert_candidates(t0, bd, tof_range=(100, 730, 5))
        print(f"  Lambert candidates: {len(cands)}")
        best_rp, best_dv, best_feas = pick_best(cands)

        comparison_status = "none"
        savings = None
        interpretation = ""

        if cands:
            print(f"\n  Best by rp match: rp={best_rp['rp_AU']:.4f} AU, dv_total={best_rp['dv_total_kms']:.1f}, tof={best_rp['tof_days']}d")
            print(f"  Best by dv:       rp={best_dv['rp_AU']:.4f} AU, dv_total={best_dv['dv_total_kms']:.1f}, tof={best_dv['tof_days']}d")

            if best_feas:
                print(f"  Best feasible:    rp={best_feas['rp_AU']:.4f} AU, dv_total={best_feas['dv_total_kms']:.1f}, tof={best_feas['tof_days']}d")

            # Comparison logic
            if best_feas:
                comparison_status = "valid"
                ls = (best_feas["dv_launch_kms"] - lunar["dv_launch_kms"]) / max(best_feas["dv_launch_kms"], 0.01)
                ts = (best_feas["dv_total_kms"] - lunar["dv_total_kms"]) / max(best_feas["dv_total_kms"], 0.01)
                savings = {"launch_saving_ratio": round(ls, 4), "total_saving_ratio": round(ts, 4),
                           "ref": "lunar_reference", "baseline": "best_feasible_lambert"}
            elif best_rp and best_rp["rp_valid"]:
                comparison_status = "partial"
                savings = None

        if comparison_status == "none":
            interpretation = ("At this fixed t0, direct Earth-to-Earth Lambert returns "
                              "do not reproduce the same deep perihelion target within the searched time range.")
        elif comparison_status == "partial":
            interpretation = ("Lambert candidates reach rp ≈ 0.3 AU but do not simultaneously "
                              "satisfy the v_inf_return ≤ 15 km/s constraint.")
        elif comparison_status == "valid":
            interpretation = ("Feasible direct Lambert candidates exist at this t0.")

        case = {
            "t0_mjd": t0,
            "lunar_reference": lunar,
            "num_candidates": len(cands),
            "best_by_rp": best_rp,
            "best_by_dv": best_dv,
            "best_feasible": best_feas,
            "comparison_status": comparison_status,
            "savings": savings,
            "interpretation": interpretation,
        }
        results.append(case)

    # Output
    summary = {
        "description": "Direct Earth-to-Earth Lambert baseline for M5 no-lunar comparison",
        "search_params": {"tof_range_days": "100-730", "step_days": 5, "branches": 4},
        "t0_cases": results,
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    json_path = out_dir / "m5_no_lunar_lambert_baseline.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n[M5 Lambert] Saved to {json_path}")

    # CSV: all candidates
    all_cands = []
    for case in results:
        all_cands.extend(search_lambert_candidates(case["t0_mjd"], bd, tof_range=(100, 730, 5)))
    csv_path = out_dir / "m5_no_lunar_lambert_baseline.csv"
    with open(csv_path, "w", newline="") as f:
        if all_cands:
            w = csv.DictWriter(f, fieldnames=all_cands[0].keys())
            w.writeheader()
            w.writerows(all_cands)
    print(f"[M5 Lambert] CSV -> {csv_path}")

    print(f"\n{'='*55}")
    print("Summary")
    print(f"{'='*55}")
    for case in results:
        l = case["lunar_reference"]
        print(f"\n  t0 = MJD {case['t0_mjd']:.0f}:")
        print(f"    Lunar: rp={l['rp_actual_AU']:.4f} AU, dv_total={l['dv_total_kms']:.1f} km/s")
        print(f"    Lambert candidates: {case['num_candidates']}")
        if case["best_by_rp"]:
            b = case["best_by_rp"]
            print(f"    Best rp match: rp={b['rp_AU']:.4f} AU, dv={b['dv_total_kms']:.1f}, tof={b['tof_days']}d, branch={b['branch']}")
        if case["best_feasible"]:
            f = case["best_feasible"]
            print(f"    Best feasible:  rp={f['rp_AU']:.4f} AU, dv={f['dv_total_kms']:.1f}, tof={f['tof_days']}d, branch={f['branch']}")
        print(f"    Comparison: {case['comparison_status']}")
        if case["savings"]:
            print(f"    Savings: total={case['savings']['total_saving_ratio']:.2%}")
        print(f"    {case['interpretation']}")


if __name__ == "__main__":
    main()
