"""
m5_no_lunar_lambert_baseline.py
================================
Direct Earth-to-Earth Lambert transfer search for M5 no-lunar comparison.
Coarse scan (5d) → fine scan (0.25d) around promising zones → Pareto frontier.

Outputs:
  data/results/m5_no_lunar_lambert_baseline.json, .csv
  data/results/m5_no_lunar_lambert_pareto.json, .csv, .png
"""

import json, os, csv, sys, math, numpy as np
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

def launch_dv_from_vinf(vinf):
    return math.sqrt(V_ESCAPE_EARTH**2 + vinf**2)


def lambert_candidate(t0_mjd, tof_days, body_data, branch, rp_target=0.3):
    """Compute a single Lambert candidate."""
    try:
        r_sun0, v_sun0 = interpolate_state_at_mjd(body_data, "Sun", t0_mjd)
        r_earth0, v_earth0 = interpolate_state_at_mjd(body_data, "Earth", t0_mjd)
        tf_mjd = t0_mjd + tof_days
        r_earth_f, v_earth_f = interpolate_state_at_mjd(body_data, "Earth", tf_mjd)
        r_sun_f, v_sun_f = interpolate_state_at_mjd(body_data, "Sun", tf_mjd)
    except Exception:
        return None

    r0 = np.array(r_earth0) - np.array(r_sun0)
    rf = np.array(r_earth_f) - np.array(r_sun_f)
    vE0 = np.array(v_earth0) - np.array(v_sun0)
    vEf = np.array(v_earth_f) - np.array(v_sun_f)
    tof_s = tof_days * 86400.0
    mu = GM_SUN

    branch_flags = {
        "prograde_short": (True, False),
        "prograde_long": (True, True),
        "retrograde_short": (False, False),
        "retrograde_long": (False, True),
    }
    if branch not in branch_flags:
        return None
    prograde, long_way = branch_flags[branch]

    try:
        v1, v2, diag = solve_lambert_universal(r0, rf, tof_s, mu, prograde=prograde, long_way=long_way)
    except Exception:
        return None

    if _norm(v1) > 1e6 or _norm(v2) > 1e6:
        return None

    a, e, rp_km, eps, h = orbital_elements_from_state(r0, v1, mu)
    rp_AU = km_to_au(rp_km)
    v_inf_depart = _norm(v1 - vE0)
    v_inf_return = _norm(v2 - vEf)
    dv_launch = launch_dv_from_vinf(v_inf_depart)
    dv_reentry = max(0, v_inf_return - V_INF_MAX)
    dv_total = dv_launch + dv_reentry
    rp_error_rel = abs(rp_AU - rp_target) / rp_target
    rp_valid = rp_error_rel < 0.10
    reentry_valid = v_inf_return <= 15

    return {
        "t0_mjd": t0_mjd,
        "tf_mjd": round(tf_mjd, 2),
        "tof_days": tof_days,
        "branch": branch,
        "a_AU": round(km_to_au(abs(a)), 6),
        "e": round(e, 6),
        "rp_AU": round(rp_AU, 6),
        "rp_error_rel": round(rp_error_rel, 6),
        "rp_valid": bool(rp_valid),
        "v_inf_depart_kms": round(v_inf_depart, 4),
        "v_inf_return_kms": round(v_inf_return, 4),
        "reentry_valid": bool(reentry_valid),
        "dv_launch_kms": round(dv_launch, 4),
        "dv_reentry_kms": round(dv_reentry, 4),
        "dv_total_kms": round(dv_total, 4),
        "constraints_satisfied": bool(rp_valid and reentry_valid and tof_days <= 730),
    }


def get_lunar_reference(t0_mjd, body_data, rp_design=0.3):
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


def compute_pareto(candidates):
    """Return list of Pareto-efficient candidates on (rp_error_rel, v_inf_return)."""
    pts = [(c["rp_error_rel"], c["v_inf_return_kms"], i) for i, c in enumerate(candidates)]
    pts.sort(key=lambda x: (x[0], x[1]))
    pareto = []
    best_y = 1e9
    for x, y, i in pts:
        if y < best_y:
            best_y = y
            pareto.append(candidates[i])
    return pareto


def plot_pareto(candidates, pareto, lunar, out_dir):
    """Save Pareto frontier PNG."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return

    fig, ax = plt.subplots(figsize=(8, 6))

    xs = [c["rp_error_rel"] for c in candidates]
    ys = [c["v_inf_return_kms"] for c in candidates]
    ax.scatter(xs, ys, s=5, alpha=0.3, label="All candidates", c="blue")

    if pareto:
        px = [c["rp_error_rel"] for c in pareto]
        py = [c["v_inf_return_kms"] for c in pareto]
        ax.plot(px, py, "r-", lw=1.5, alpha=0.7, label="Pareto frontier")

    # Threshold lines
    ax.axhline(15, color="green", ls="--", lw=0.8, alpha=0.6, label="v_inf_return=15 km/s")
    for tol, ls, clr in [(0.05, ":", "orange"), (0.10, "--", "purple")]:
        ax.axvline(tol, color=clr, ls=ls, lw=0.8, alpha=0.4,
                   label=f"rp_error={tol:.0%}")

    # Lunar reference
    if lunar:
        ax.scatter([lunar["rp_error_rel"]], [lunar["v_rel_return_kms"]],
                   c="red", s=80, marker="*", zorder=8, label="Lunar reference")

    ax.set_xlabel("rp error (relative to 0.3 AU)")
    ax.set_ylabel("Return v_inf (km/s)")
    ax.set_title("Direct Lambert: rp error vs return v_inf")
    ax.legend(fontsize=7)
    ax.grid(alpha=0.3)

    plt.savefig(out_dir / "m5_no_lunar_lambert_pareto.png", dpi=120, bbox_inches="tight")
    plt.close(fig)


def search_lambert(t0_mjd, body_data, rp_target=0.3):
    """Two-stage search: coarse (5d) then fine (0.25d) around promising zones."""
    branches = ["prograde_short", "prograde_long", "retrograde_short", "retrograde_long"]
    all_candidates = []

    # Coarse scan
    print("  Coarse scan (5d step)...")
    coarse_tofs = list(range(100, 731, 5))
    for tof in coarse_tofs:
        for br in branches:
            c = lambert_candidate(t0_mjd, tof, body_data, br, rp_target)
            if c:
                all_candidates.append(c)
    print(f"    {len(all_candidates)} candidates")

    # Identify promising zones: best rp match and v_inf_return near 15
    if not all_candidates:
        return all_candidates, [], []

    # Score: penalize rp error + excess return v_inf
    def score(c):
        return 100 * abs(c["rp_error_rel"] - 0) + 10 * max(0, c["v_inf_return_kms"] - 15) + c["dv_total_kms"]

    all_candidates.sort(key=score)
    top_n = min(20, len(all_candidates))
    promising = all_candidates[:top_n]
    fine_centers = set(p["tof_days"] for p in promising)

    print(f"  Fine scan ({len(fine_centers)} promising zones, 0.25d step)...")
    fine_count = 0
    for center in fine_centers:
        fine_tofs = np.arange(max(100, center - 8), min(730, center + 8) + 0.01, 0.25)
        for tof in fine_tofs:
            tof_rounded = round(tof, 2)
            for br in branches:
                c = lambert_candidate(t0_mjd, tof_rounded, body_data, br, rp_target)
                if c:
                    all_candidates.append(c)
                    fine_count += 1
    print(f"    {fine_count} fine candidates")

    # Remove duplicates (same t0, tof, branch)
    seen = set()
    deduped = []
    for c in all_candidates:
        key = (c["t0_mjd"], round(c["tof_days"], 2), c["branch"])
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    all_candidates = deduped
    print(f"    {len(all_candidates)} unique candidates total")

    pareto = compute_pareto(all_candidates)
    return all_candidates, pareto, coarse_tofs


def main():
    bd = fetch_sem_vectors(use_cache=True)
    t0s = [61066.0, 61154.0]
    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    results = []
    for t0 in t0s:
        print(f"\n{'='*55}")
        print(f"  t0 = MJD {t0:.0f}")
        print(f"{'='*55}")

        lunar = get_lunar_reference(t0, bd)
        print(f"  Lunar: rp={lunar['rp_actual_AU']:.4f} AU, dv_total={lunar['dv_total_kms']:.1f} km/s")

        cands, pareto, _ = search_lambert(t0, bd)
        feasible = [c for c in cands if c["constraints_satisfied"]]
        near_feasible = [c for c in cands if c["rp_valid"] and 15 < c["v_inf_return_kms"] <= 25]

        # Best picks
        best_rp = min(cands, key=lambda c: abs(c["rp_AU"] - 0.3)) if cands else None
        best_vinf = min(cands, key=lambda c: abs(c["v_inf_return_kms"] - 15)) if cands else None
        best_dv = min(cands, key=lambda c: c["dv_total_kms"]) if cands else None
        best_feas = min(feasible, key=lambda c: c["dv_total_kms"]) if feasible else None

        # Comparison status
        if feasible:
            comp_status = "valid"
            ref = feasible[0]  # best by dv
            ls = (ref["dv_launch_kms"] - lunar["dv_launch_kms"]) / max(ref["dv_launch_kms"], 0.01)
            ts = (ref["dv_total_kms"] - lunar["dv_total_kms"]) / max(ref["dv_total_kms"], 0.01)
            savings = {"launch_saving_ratio": round(ls, 4), "total_saving_ratio": round(ts, 4)}
            interp = "Feasible direct Lambert candidates exist at this t0."
        elif near_feasible:
            comp_status = "partial_tradeoff"
            savings = None
            interp = ("Lambert reaches rp≈0.3 AU but return v_inf exceeds 15 km/s. "
                      "This is a trade-off between perihelion accuracy and reentry speed.")
        elif best_rp and best_rp["rp_valid"]:
            comp_status = "partial_tradeoff"
            savings = None
            interp = "Lambert reaches rp≈0.3 AU but return v_inf greatly exceeds 15 km/s."
        else:
            comp_status = "invalid_no_matching_perihelion"
            savings = None
            interp = "No Lambert candidate matches both rp≈0.3 AU and Earth return."

        print(f"  Candidates: {len(cands)}, feasible={len(feasible)}, near_feasible={len(near_feasible)}")
        if best_rp:
            print(f"  Best rp:     rp={best_rp['rp_AU']:.4f} AU, tof={best_rp['tof_days']}d, vinf_ret={best_rp['v_inf_return_kms']:.2f}")
        if best_feas:
            print(f"  Best feas:   rp={best_feas['rp_AU']:.4f} AU, dv={best_feas['dv_total_kms']:.1f}")
        print(f"  Status: {comp_status}")
        print(f"  {interp}")

        case = {
            "t0_mjd": t0,
            "lunar_reference": lunar,
            "num_candidates": len(cands),
            "num_feasible": len(feasible),
            "num_near_feasible": len(near_feasible),
            "best_by_rp": best_rp,
            "best_by_return_vinf": best_vinf,
            "best_by_dv": best_dv,
            "best_feasible": best_feas,
            "num_pareto": len(pareto),
            "comparison_status": comp_status,
            "savings": savings,
            "interpretation": interp,
        }
        results.append(case)

        # Pareto plot
        plot_pareto(cands, pareto, lunar, out_dir)

    # Save JSON
    summary = {
        "search_config": {"tof_coarse_step_days": 5, "tof_fine_step_days": 0.25,
                          "branches": ["prograde_short", "prograde_long", "retrograde_short", "retrograde_long"]},
        "t0_cases": results,
    }
    json_path = out_dir / "m5_no_lunar_lambert_baseline.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n[M5] -> {json_path}")

    # CSV all candidates
    all_c = []
    for case in results:
        _, pareto, _ = search_lambert(case["t0_mjd"], bd)  # re-evaluate
        all_c.extend(pareto)
    csv_path = out_dir / "m5_no_lunar_lambert_baseline.csv"
    with open(csv_path, "w", newline="") as f:
        if all_c:
            w = csv.DictWriter(f, fieldnames=all_c[0].keys())
            w.writeheader()
            w.writerows(all_c)
    print(f"[M5] CSV -> {csv_path}")

    # Pareto JSON/CSV
    for case in results:
        _, pareto, _ = search_lambert(case["t0_mjd"], bd)
        pj = {"t0_mjd": case["t0_mjd"], "num_pareto": len(pareto), "pareto_candidates": pareto}
        with open(out_dir / f"m5_no_lunar_lambert_pareto_t0{int(case['t0_mjd'])}.json", "w") as f:
            json.dump(pj, f, indent=2)
        if pareto:
            pc = out_dir / f"m5_no_lunar_lambert_pareto_t0{int(case['t0_mjd'])}.csv"
            with open(pc, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=pareto[0].keys())
                w.writeheader()
                w.writerows(pareto)
            print(f"[M5] Pareto -> {pc}")


if __name__ == "__main__":
    main()
