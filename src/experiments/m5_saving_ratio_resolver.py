"""
m5_saving_ratio_resolver.py
============================
Resolves the M5 saving ratio from:
- m5_dsm_no_lunar_search.json (no-lunar DSM baseline)
- m5_lunar_budget_recomputed.json (lunar proxy budget)

Saving ratio = (dv_no_lunar - dv_lunar) / dv_no_lunar

Positive = lunar saves fuel (better)
Negative = no-lunar baseline has lower total Δv (lunar trajectory is worse)

Output: data/results/m5_saving_ratio_resolved.json
"""

import json, os, sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
RESULTS = _REPO / "data" / "results"


def _load(name):
    p = RESULTS / name
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    print("=" * 66)
    print("M5 saving ratio resolver")
    print("=" * 66)

    dsm = _load("m5_dsm_no_lunar_search.json")
    lunar = _load("m5_lunar_budget_recomputed.json")

    if dsm is None:
        print("[ERROR] DSM no-lunar search results not found.")
        sys.exit(1)
    if lunar is None:
        print("[ERROR] Lunar budget recompute not found.")
        sys.exit(1)

    dv_lunar = lunar["budget"]["total_dv_proxy_kms"]
    print(f"\n  Lunar total dv proxy: {dv_lunar:.4f} km/s")
    print(f"    launch_proxy  = {lunar['budget']['launch_proxy_kms']:.4f}")
    print(f"    lunar_residual= {lunar['budget']['lunar_residual_kms']:.4f}")
    print(f"    return_brake  = {lunar['budget']['return_braking_proxy_kms']:.4f}")
    print(f"    return_vinf   = {lunar['budget']['return_vinf_kms']:.4f}")
    print()

    n_fair = dsm.get("num_fair", 0)
    n_near = dsm.get("num_near_feasible", 0)
    n_total = dsm.get("num_candidates", 0)

    print(f"  DSM candidates:   {n_total}")
    print(f"  Strict fair:      {n_fair}")
    print(f"  Near-feasible:    {n_near}")
    print()

    best = dsm.get("best_strict_fair")
    best_near = dsm.get("best_near_feasible")

    # Additional best-by-metric candidates
    best_peri = dsm.get("best_by_perihelion")
    best_vinf = dsm.get("best_by_return_vinf")
    best_dv = dsm.get("best_by_total_dv")
    best_bal = dsm.get("best_balanced")

    formal_saving_ratio = None
    reference_ratio = None
    status = "no_baseline"

    if best and best.get("fair"):
        dv_no = best["total_dv_proxy_kms"]
        formal_saving_ratio = (dv_no - dv_lunar) / dv_no if dv_no > 0 else None
        status = "strict_fair_saving_ratio_found"
        print(f"  STRICT FAIR BASELINE:")
        print(f"    t0={best['t0_mjd']:.0f} tof1={best['tof1_days']:.0f} tof2={best['tof2_days']:.0f}")
        print(f"    dv_no_lunar = {dv_no:.4f} km/s")
        print(f"    dv_lunar    = {dv_lunar:.4f} km/s")
        print(f"    saving_ratio = {formal_saving_ratio:.4f} ({formal_saving_ratio*100:.1f}%)")
        if formal_saving_ratio < 0:
            print("    [NEGATIVE] lunar trajectory has HIGHER total dv than no-lunar baseline.")
            print("    This is physically meaningful: the lunar trajectory's extreme return")
            print("    speed (77.88 km/s v_rel_earth) dominates the budget.")
    elif best_near:
        dv_no = best_near["total_dv_proxy_kms"]
        reference_ratio = (dv_no - dv_lunar) / dv_no if dv_no > 0 else None
        status = "near_feasible_reference_only"
        print(f"  NEAR-FEASIBLE BASELINE:")
        print(f"    dv_no_lunar = {dv_no:.4f} km/s")
        print(f"    ref_ratio   = {reference_ratio:.4f} ({reference_ratio*100:.1f}%)")
        print("    NOT valid as formal saving ratio.")
    else:
        print(f"  No fair or near-feasible baseline found.")
        status = "no_fair_or_near_feasible_baseline_after_direct_and_dsm_search"
        if best_dv:
            dv_no = best_dv["total_dv_proxy_kms"]
            print(f"  Best invalid (by total dv): tot={dv_no:.4f}")
        if best_peri:
            print(f"  Best invalid (by perihelion): peri={best_peri['perihelion_AU']:.4f}")
        if best_vinf:
            print(f"  Best invalid (by return v_inf): vinf={best_vinf['return_vinf_kms']:.2f}")

    # Candidate listing for best-in-class
    def fmt_cand(c, label=""):
        if c is None:
            return None
        return {
            "label": label,
            "t0_mjd": c["t0_mjd"],
            "tof1_days": c["tof1_days"],
            "tof2_days": c["tof2_days"],
            "r_DSM_AU": c.get("r_DSM_AU"),
            "departure_vinf_kms": c["departure_vinf_kms"],
            "dsm_delta_v_kms": c["dsm_delta_v_kms"],
            "return_vinf_kms": c["return_vinf_kms"],
            "return_braking_kms": c["return_braking_proxy_kms"],
            "perihelion_AU": c["perihelion_AU"],
            "total_dv_proxy_kms": c["total_dv_proxy_kms"],
            "fair": c["fair"],
            "near_feasible": c["near_feasible"],
        }

    out = {
        "task": "M5 saving ratio resolver",
        "lunar_budget_source": "m5_lunar_budget_recomputed.json",
        "dsm_budget_source": "m5_dsm_no_lunar_search.json",
        "budget_definition": "total = departure_vinf + dsm_delta_v + max(0, return_vinf - 15)",
        "lunar_total_dv_proxy_kms": dv_lunar,
        "lunar_budget": lunar["budget"],
        "dsm_total_candidates": n_total,
        "dsm_fair_count": n_fair,
        "dsm_near_feasible_count": n_near,
        "dsm_best_strict_fair": fmt_cand(best, "best_strict_fair"),
        "dsm_best_near_feasible": fmt_cand(best_near, "best_near_feasible"),
        "dsm_best_by_perihelion": fmt_cand(best_peri, "best_perihelion"),
        "dsm_best_by_return_vinf": fmt_cand(best_vinf, "best_return_vinf"),
        "dsm_best_by_total_dv": fmt_cand(best_dv, "best_total_dv"),
        "dsm_best_balanced": fmt_cand(best_bal, "best_balanced"),
        "formal_saving_ratio": (round(formal_saving_ratio, 6)
                                if formal_saving_ratio is not None else None),
        "reference_saving_ratio": (round(reference_ratio, 6)
                                    if reference_ratio is not None else None),
        "status": status,
        "conclusion": "",
    }

    # Conclusion text
    if formal_saving_ratio is not None:
        ratio_pct = formal_saving_ratio * 100
        out["conclusion"] = (
            f"Strict fair no-lunar DSM baseline FOUND. "
            f"Best candidate: t0={best['t0_mjd']:.0f}, "
            f"tof1={best['tof1_days']:.0f}d, tof2={best['tof2_days']:.0f}d, "
            f"dsm_dv={best['dsm_delta_v_kms']:.2f} km/s, "
            f"return_vinf={best['return_vinf_kms']:.2f} km/s. "
            f"Total no-lunar proxy = {best['total_dv_proxy_kms']:.2f} km/s. "
            f"Lunar proxy = {dv_lunar:.2f} km/s. "
            f"Formal saving ratio = {formal_saving_ratio:.4f} ({ratio_pct:.1f}%)."
        )
        if formal_saving_ratio < 0:
            out["conclusion"] += (
                " The saving ratio is NEGATIVE, meaning the no-lunar baseline "
                "has lower total proxy Δv than the lunar-assisted trajectory. "
                "This is dominated by the lunar trajectory's extreme return speed "
                "(v_rel_earth = 77.88 km/s), which incurs a 62.88 km/s braking "
                "penalty under the uniform budget proxy."
            )
    elif reference_ratio is not None:
        out["conclusion"] = (
            f"Near-feasible no-lunar DSM baseline found. "
            f"Reference ratio = {reference_ratio:.4f}. "
            "NOT valid as formal M5 saving ratio. "
            "No strict fair baseline satisfying all constraints."
        )
    else:
        out["conclusion"] = (
            "No fair or near-feasible no-lunar baseline found "
            "after direct and DSM searches. "
            "M5.5 requirement cannot be formally satisfied."
        )

    jp = RESULTS / "m5_saving_ratio_resolved.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
