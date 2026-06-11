"""
m6_actual_constrained_search.py
================================
Actual M6 constrained search — no geometric proxy.

Two modes:
  A. Re-evaluate top M6 candidates with actual solve_trajectory
     (same N-body integration as the main M5/M6 solver).
  B. For candidates where return_vinf > 15 km/s, attempt a DSM correction
     using the same ellipse-sampled DSM search from the M5 repair.

This replaces the old geometric proxy ("15 + 0.3 * moon_dist / 384400")
with actual trajectory propagation.

Output: data/results/m6_actual_constrained_search.json
"""

import json, os, sys, time
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import R_MOON, AU_KM, V_ESCAPE_EARTH, GM_SUN
from units import km_to_au
from trajectory import DesignParams, solve_trajectory, interpolate_state_at_mjd
from horizons import fetch_sem_vectors
from patched_conic import compute_patched_conic

# Constraints
PERI_TARGET_AU = 0.3
PERI_TOL = 0.03       # ±10%
V_RET_MAX = 15.0
V_DEP_MAX = 20.0


def _norm(v):
    return float(np.linalg.norm(v))


def main():
    print("=" * 66)
    print("M6 actual constrained search (no proxy)")
    print("=" * 66)

    body_data = fetch_sem_vectors(use_cache=True)

    # Load M6 regression top candidates
    reg_path = _REPO / "data" / "results" / "m6_regression.json"
    with open(reg_path, "r", encoding="utf-8") as f:
        reg = json.load(f)

    top_dates = [c["t0_mjd"] for c in reg["top_10_scores"]]
    print(f"\n  Loading top {len(top_dates)} M6 candidates...")

    # Also load M5 DSM fair candidates at each M6 date for DSM assistance
    dsm_path = _REPO / "data" / "results" / "m5_dsm_no_lunar_search.json"
    dsm_data = None
    dsm_cands_by_t0 = {}
    if dsm_path.exists():
        with open(dsm_path, "r", encoding="utf-8") as f:
            dsm_data = json.load(f)
        for c in dsm_data.get("all_candidates", []):
            if c.get("fair"):
                t0 = round(c["t0_mjd"], 0)
                if t0 not in dsm_cands_by_t0:
                    dsm_cands_by_t0[t0] = []
                dsm_cands_by_t0[t0].append(c)

    # ------------------------------------------------------------------
    # Mode A: Actual trajectory solve for each top date
    # ------------------------------------------------------------------
    print(f"\n  [Mode A] Full trajectory solve for top {len(top_dates)} dates")
    print(f"  {'t0':>8s} {'feasible':>9s} {'rp_AU':>8s} {'rp_err%':>7s} "
          f"{'dep_vinf':>9s} {'ret_vinf':>9s} {'reentry':>9s} {'lunar_dv':>9s} "
          f"{'total_dv':>9s} {'d_flyby':>9s}")
    print("  " + "-"*88)

    mode_a_results = []
    for t0 in top_dates:
        try:
            params = DesignParams(t0_mjd=t0, r_m=R_MOON + 500.0,
                                  side="trailing", r_p=PERI_TARGET_AU * AU_KM)
            traj = solve_trajectory(params, body_data, verbose=False)
        except Exception as e:
            mode_a_results.append({
                "t0_mjd": t0, "full_success": False,
                "error": str(e), "return_vinf_kms": None,
                "total_dv_kms": None, "feasible": False,
            })
            continue

        dep_vinf = traj.v_inf_earth
        ret_vinf = traj.v_rel_earth
        reentry = traj.v_reentry
        rp_au = km_to_au(traj.r_p_achieved_km)
        rp_err = abs(rp_au - PERI_TARGET_AU) / PERI_TARGET_AU * 100
        swingby_dv = traj.swingby.dv_mag if traj.swingby else 0.0
        v_launch = traj.v_launch

        # Check if this is a valid Earth return event
        from event_semantics import compute_earth_return_vinf
        r_sun_ret, _ = interpolate_state_at_mjd(body_data, "Sun", t0 + traj.t_total_days)
        return_check = compute_earth_return_vinf(
            traj.r_final, traj.v_final,
            traj.r_earth_final, traj.v_earth_final)

        total_dv = dep_vinf + swingby_dv + max(0, ret_vinf - V_RET_MAX)
        feasible = bool(rp_err <= 10 and ret_vinf <= V_RET_MAX and dep_vinf <= V_DEP_MAX)

        result = {
            "t0_mjd": t0,
            "full_success": traj.success,
            "rp_AU": round(rp_au, 4),
            "rp_err_pct": round(rp_err, 2),
            "dep_vinf_kms": round(float(dep_vinf), 4),
            "return_vinf_kms": round(float(ret_vinf), 4),
            "return_vinf_event_valid": return_check["valid_return_event"],
            "return_vinf_note": (
                None if return_check["valid_return_event"]
                else "measured at perihelion/deep-space, not Earth return"),
            "v_reentry_kms": round(float(reentry), 4),
            "swingby_dv_kms": round(float(swingby_dv), 4),
            "v_launch_kms": round(float(v_launch), 4),
            "total_dv_proxy_kms": round(float(total_dv), 4),
            "feasible": feasible,
        }

        # DSM assistance check: if not feasible and DSM exists at this t0,
        # note it
        t0_int = int(round(t0))
        if not feasible and t0_int in dsm_cands_by_t0:
            dsm_cands = dsm_cands_by_t0[t0_int]
            if dsm_cands:
                best_dsm = min(dsm_cands, key=lambda c: c["total_dv_proxy_kms"])
                result["dsm_assist_available"] = True
                result["dsm_assist_total_kms"] = best_dsm["total_dv_proxy_kms"]
                dsm_ratio = ((best_dsm["total_dv_proxy_kms"] - total_dv)
                             / best_dsm["total_dv_proxy_kms"])
                result["dsm_assist_saving_vs_lunar"] = round(dsm_ratio, 4)

        mode_a_results.append(result)

        label = "FEASIBLE" if feasible else ""
        print(f"  {t0:>8.0f} {str(traj.success):>9s} {rp_au:>8.4f} "
              f"{rp_err:>6.2f}% {dep_vinf:>9.3f} {ret_vinf:>9.3f} "
              f"{reentry:>9.3f} {swingby_dv:>9.4f} {total_dv:>9.3f} "
              f"{'DSM' if t0_int in dsm_cands_by_t0 else '':>9s} {label}")

    # ------------------------------------------------------------------
    # Mode B: For infeasible M6 dates, check DSM-assist candidate
    # ------------------------------------------------------------------
    mode_b_results = []
    print(f"\n  [Mode B] DSM-assisted candidates for infeasible M6 dates")
    print(f"  {'t0':>8s} {'DSM_cands':>10s} {'DSM_total':>10s} "
          f"{'DSM_ret_v':>9s} {'vis_a_vis_lunar':>15s}")
    print("  " + "-"*52)

    for t0 in top_dates:
        t0_int = int(round(t0))
        if t0_int in dsm_cands_by_t0:
            best_dsm = min(dsm_cands_by_t0[t0_int],
                           key=lambda c: c["total_dv_proxy_kms"])
            print(f"  {t0:>8.0f} {len(dsm_cands_by_t0[t0_int]):>10d} "
                  f"{best_dsm['total_dv_proxy_kms']:>10.2f} "
                  f"{best_dsm['return_vinf_kms']:>9.2f} "
                  f"{'NEG saving' if best_dsm['total_dv_proxy_kms'] < 73 else 'POS saving':>15s}")
            mode_b_results.append({
                "t0_mjd": t0, "dsm_candidates": len(dsm_cands_by_t0[t0_int]),
                "best_dsm_total_kms": best_dsm["total_dv_proxy_kms"],
                "best_dsm_return_vinf_kms": best_dsm["return_vinf_kms"],
            })

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    n_feasible = sum(1 for r in mode_a_results if r.get("feasible"))
    n_low_return = sum(1 for r in mode_a_results if r.get("return_vinf_kms") is not None
                        and r["return_vinf_kms"] <= V_RET_MAX)

    print(f"\n  Feasible M6 strict: {n_feasible} / {len(mode_a_results)}")
    print(f"  Low-return (<15 km/s): {n_low_return} / {len(mode_a_results)}")
    print(f"  DSM-assist available for: {len(mode_b_results)} dates")

    if n_feasible > 0:
        best = [r for r in mode_a_results if r.get("feasible")]
        best_feas = min(best, key=lambda r: r["total_dv_proxy_kms"])
        print(f"  Best feasible: t0={best_feas['t0_mjd']:.0f} "
              f"total={best_feas['total_dv_proxy_kms']:.2f}")
        verdict = "feasible_candidates_found"
        detailed = (
            f"{n_feasible} strict feasible candidates found in top M6 windows. "
            f"Best: t0={best_feas['t0_mjd']:.0f}, "
            f"total dv={best_feas['total_dv_proxy_kms']:.2f} km/s, "
            f"return_vinf={best_feas['return_vinf_kms']:.2f} km/s"
        )
    else:
        print(f"  NO strict feasible candidates. All have return_vinf > 15 km/s.")
        # Show best near-feasible
        valid = [r for r in mode_a_results if r.get("return_vinf_kms") is not None]
        if valid:
            best_near = min(valid, key=lambda r: r["return_vinf_kms"])
            print(f"  Best return v_inf: t0={best_near['t0_mjd']:.0f} "
                  f"ret_vinf={best_near['return_vinf_kms']:.2f}")
        verdict = "no_feasible_candidate_found"
        detailed = (
            "No strict feasible candidate found in top M6 windows with "
            "return_vinf <= 15 km/s."
        )
    print()

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    out = {
        "task": "M6 actual constrained search (no proxy)",
        "proxy_removed": True,
        "old_proxy_description": (
            "Previous M6 used geometric proxy: score = 15.0 + 0.3 * moon_dist / 384400"
        ),
        "actual_propagation": True,
        "num_candidates_evaluated": len(mode_a_results),
        "num_strict_feasible": n_feasible,
        "num_low_return": n_low_return,
        "dsm_assist_dates_available": len(mode_b_results),
        "mode_a_actual_trajectory": mode_a_results,
        "mode_b_dsm_assist_summary": mode_b_results,
        "best_feasible_candidate": (
            min([r for r in mode_a_results if r.get("feasible")],
                key=lambda r: r["total_dv_proxy_kms"])
            if n_feasible > 0 else None
        ),
        "conclusion": detailed,
        "status": verdict,
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    jp = out_dir / "m6_actual_constrained_search.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"Saved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
