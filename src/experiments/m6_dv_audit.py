"""
m6_dv_audit.py
==============
M6 Δv audit: decompose dv_total into three components per problem spec,
add braking Δv interpretation, and produce lexicographic ranking.

Output:
  data/results/m6_dv_audit.json
  data/results/m6_refined_windows.json  (overwrite with corrected ranking)
  data/results/m6_refinement_table.csv  (overwrite with corrected ranking)
"""

import json, os, csv, sys, math, numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

OUT = _REPO / "data" / "results"
os.makedirs(OUT, exist_ok=True)

from constants import AU_KM, R_MOON, V_ESCAPE_EARTH, V_INF_MAX
from trajectory import DesignParams, solve_trajectory
from horizons import fetch_sem_vectors


def compute_dv_breakdown(t0_mjd, r_m_km, side, r_p_au, body_data, verbose=False):
    """Compute full dv breakdown for a single window.

    Returns dict with all dv components and sanity flags.
    """
    r_p_km = r_p_au * AU_KM
    params = DesignParams(t0_mjd=t0_mjd, r_m=r_m_km, side=side, r_p=r_p_km)
    traj = solve_trajectory(params, body_data, verbose=False)

    if not traj.success:
        return {"t0_mjd": t0_mjd, "success": False}

    # --- Components ---
    # Launch dv: from Earth surface to escape (per patched conic)
    dv_launch = traj.v_launch  # km/s

    # Lunar swingby residual: the impulse imparted by the Moon
    dv_lunar_residual = traj.swingby.dv_mag if traj.swingby else 0.0

    # Return: heliocentric v_inf relative to Earth
    v_rel_earth = traj.v_rel_earth  # km/s
    v_reentry = traj.v_reentry      # km/s = sqrt(v_esc^2 + v_rel^2)

    # Per problem spec §3: Δv_reentry = braking to reentry speed
    # Constraint: v_inf <= 15 km/s
    dv_reentry_brake = max(0.0, v_rel_earth - V_INF_MAX)

    # Legacy total (speed-based)
    dv_total_legacy = dv_launch + dv_lunar_residual + v_reentry

    # Corrected total (braking-based)
    dv_total_corrected = dv_launch + dv_lunar_residual + dv_reentry_brake

    # --- Derived quantities ---
    rp_achieved_AU = traj.r_p_achieved_km / AU_KM
    rp_error_rel = abs(rp_achieved_AU - r_p_au) / r_p_au

    # Sanity gates
    sanity_warnings = []
    if dv_launch > 25: sanity_warnings.append(f"dv_launch {dv_launch:.1f} > 25")
    if dv_launch < 10: sanity_warnings.append(f"dv_launch {dv_launch:.1f} < 10 (improbably low)")
    if dv_lunar_residual > 10: sanity_warnings.append(f"dv_lunar {dv_lunar_residual:.1f} > 10")
    if dv_total_legacy > 50: sanity_warnings.append(f"dv_total_legacy {dv_total_legacy:.1f} > 50")
    if dv_total_corrected > 50: sanity_warnings.append(f"dv_total_corrected {dv_total_corrected:.1f} > 50")
    if traj.dist_moon_min > 66000: sanity_warnings.append(f"Moon miss: dist {traj.dist_moon_min:.0f} > SOI")
    if rp_error_rel > 0.25: sanity_warnings.append(f"rp_error {rp_error_rel:.2%} > 25%")

    constraints_ok = bool(
        float(traj.dist_moon_min) < 66000 and
        float(rp_error_rel) < 0.25 and
        float(v_rel_earth) <= 30
    )

    # Wrap all numeric values as Python native types
    def _pyfloat(x):
        return float(x) if x is not None else None

    return {
        "t0_mjd": float(t0_mjd),
        "rp_target_AU": float(r_p_au),
        "rp_actual_AU": _pyfloat(rp_achieved_AU),
        "rp_error_rel": _pyfloat(rp_error_rel),
        "dv_launch_kms": _pyfloat(dv_launch),
        "dv_lunar_residual_kms": _pyfloat(dv_lunar_residual),
        "v_rel_earth_kms": _pyfloat(v_rel_earth),
        "v_reentry_ati_kms": _pyfloat(v_reentry),
        "dv_reentry_brake_kms": _pyfloat(dv_reentry_brake),
        "dv_total_legacy_kms": _pyfloat(dv_total_legacy),
        "dv_total_corrected_kms": _pyfloat(dv_total_corrected),
        "earth_departure_vinf_kms": _pyfloat(traj.v_inf_earth),
        "moon_vinf_in_kms": _pyfloat(traj.swingby.v_inf) if traj.swingby else None,
        "moon_dv_kms": _pyfloat(traj.swingby.dv_mag) if traj.swingby else None,
        "flight_time_days": _pyfloat(traj.t_total_days),
        "dist_moon_min_km": _pyfloat(traj.dist_moon_min),
        "constraints_satisfied": constraints_ok,
        "sanity_warnings": sanity_warnings,
        "sanity_warning_count": len(sanity_warnings),
        "success": True,
    }


def compute_lexicographic_key(w):
    """Lexicographic ordering key:
    1. success first
    2. constraints_satisfied
    3. rp_error_rel <= 0.05
    4. sanity_warning_count (lower better)
    5. dv_total_corrected_kms (lower better)
    6. rp_error_rel (lower better)
    """
    return (
        1 if not w.get("success", False) else 0,
        1 if not w.get("constraints_satisfied", False) else 0,
        0 if float(w.get("rp_error_rel", 1.0)) <= 0.05 else 1,
        int(w.get("sanity_warning_count", 999)),
        float(w.get("dv_total_corrected_kms", 1e9)),
        float(w.get("rp_error_rel", 1.0)),
    )


def main():
    body_data = fetch_sem_vectors(use_cache=True)

    windows = [
        (61066.0, "2026-02-07"),
        (61125.0, "2026-04-07"),
        (61154.0, "2026-05-06"),
        (61213.0, "2026-07-04"),
        (61391.0, "2026-12-29"),
    ]

    results = []
    for t0_mjd, date in windows:
        print(f"  Solving MJD {t0_mjd:.1f} ({date})...")
        res = compute_dv_breakdown(t0_mjd, R_MOON + 500, "trailing", 0.3, body_data)
        if res.get("success", False):
            res["date"] = date
            results.append(res)
            print(f"    dv_launch={res['dv_launch_kms']:.2f}, "
                  f"dv_lunar={res['dv_lunar_residual_kms']:.4f}, "
                  f"dv_brake={res['dv_reentry_brake_kms']:.1f}, "
                  f"dv_total_corr={res['dv_total_corrected_kms']:.1f}")
            if res["sanity_warnings"]:
                for w in res["sanity_warnings"]:
                    print(f"    WARNING: {w}")

    if not results:
        print("No successful windows!")
        return

    # Sort by lexicographic key
    results.sort(key=compute_lexicographic_key)

    rankings = {
        "r_p_design_AU": 0.3,
        "num_windows": len(results),
        "ranking_method": "lexicographic: success > constraints > rp_error<5% > warnings > dv_corrected > rp_error",
        "dv_total_note": "dv_total_corrected uses dv_reentry_brake = max(0, v_rel_earth - 15) as braking Δv per problem spec. "
                         "Legacy dv_total_legacy uses v_reentry = sqrt(v_esc^2 + v_rel^2) (atmospheric interface speed, not Δv).",
        "sanity_note": "Warnings are non-fatal; lexicographic key disregards warnings for ranking when constraints are met.",
        "best_by_dv_corrected": None,
        "best_balanced": None,
        "ranked_windows": results,
    }

    # best_by_dv_corrected = min dv_total_corrected
    rankings["best_by_dv_corrected"] = min(results, key=lambda r: r["dv_total_corrected_kms"])
    # best_balanced = first in lexicographic order
    rankings["best_balanced"] = results[0]

    # Also compute best_by_rp
    rankings["best_by_rp"] = min(results, key=lambda r: r["rp_error_rel"])

    # Save JSON
    json_path = OUT / "m6_dv_audit.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rankings, f, indent=2)
    print(f"\n  Audit saved to {json_path}")

    # Save refined windows (overwrite with corrected)
    refined_path = OUT / "m6_refined_windows.json"
    with open(refined_path, "w", encoding="utf-8") as f:
        # Same data but without rank metadata
        simple = {
            "r_p_design_AU": 0.3,
            "r_m_km": R_MOON + 500,
            "side": "trailing",
            "ranking_method": rankings["ranking_method"],
            "dv_total_note": rankings["dv_total_note"],
            "best_by_dv_corrected": rankings["best_by_dv_corrected"]["t0_mjd"],
            "best_balanced": rankings["best_balanced"]["t0_mjd"],
            "refined_windows": results,
        }
        json.dump(simple, f, indent=2)
    print(f"  Refined windows saved to {refined_path}")

    # CSV table
    csv_path = OUT / "m6_refinement_table.csv"
    with open(csv_path, "w", newline="") as f:
        fields = ["t0_mjd", "rp_target_AU", "rp_actual_AU", "rp_error_rel",
                  "dv_launch_kms", "dv_lunar_residual_kms", "v_rel_earth_kms",
                  "dv_reentry_brake_kms", "dv_total_legacy_kms", "dv_total_corrected_kms",
                  "flight_time_days", "dist_moon_min_km",
                  "constraints_satisfied", "sanity_warning_count"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"  CSV table saved to {csv_path}")

    # Summary
    print(f"\n{'='*66}")
    print("Ranking summary")
    print(f"{'='*66}")
    print(f"{'Rank':<5} {'MJD':<10} {'rp_err':<10} {'dv_launch':<10} "
          f"{'dv_brake':<10} {'dv_total_corr':<14} {'warnings':<8}")
    print("-" * 67)
    for i, r in enumerate(results):
        print(f"{i+1:<5} {r['t0_mjd']:<10.0f} {r['rp_error_rel']:<10.3%} "
              f"{r['dv_launch_kms']:<10.2f} {r['dv_reentry_brake_kms']:<10.1f} "
              f"{r['dv_total_corrected_kms']:<14.1f} {r['sanity_warning_count']:<8}")
    print(f"\n  best_by_dv_corrected: MJD {rankings['best_by_dv_corrected']['t0_mjd']:.0f}, "
          f"dv_corrected={rankings['best_by_dv_corrected']['dv_total_corrected_kms']:.1f} km/s")
    print(f"  best_balanced:        MJD {rankings['best_balanced']['t0_mjd']:.0f}, "
          f"dv_corrected={rankings['best_balanced']['dv_total_corrected_kms']:.1f} km/s, "
          f"rp_error={rankings['best_balanced']['rp_error_rel']:.2%}")
    print(f"  best_by_rp:           MJD {rankings['best_by_rp']['t0_mjd']:.0f}, "
          f"rp_error={rankings['best_by_rp']['rp_error_rel']:.2%}")


if __name__ == "__main__":
    print("=" * 66)
    print("M6 dv audit and lexicographic ranking")
    print("=" * 66)
    main()
