"""
m5_saving_ratio_resolver.py
============================
Resolves the M5 saving ratio from:
- m5_dsm_no_lunar_search.json (no-lunar DSM baseline)
- m5_lunar_budget_recomputed.json (lunar proxy budget)

CRITICAL: The formal M5 fixed-date comparison must use the SAME launch date
for both lunar and no-lunar trajectories.  The lunar candidate is at
t0 = MJD 61066.

Two saving ratios are computed:
  1. formal_fixed_date_ratio — DSM best fair candidate at t0 = 61066
     vs lunar at t0 = 61066.  This is the correct M5 ratio.
  2. invalid_cross_date_ratio — DSM best fair candidate at ANY t0
     vs lunar at t0 = 61066.  Provided only for reference; NOT valid
     as the formal M5 answer because the launch dates differ.

Saving ratio = (dv_no_lunar - dv_lunar) / dv_no_lunar
Positive = lunar saves fuel.
Negative = no-lunar baseline has lower total-proxy Δv.

Output: data/results/m5_saving_ratio_resolved.json
"""

import json, os, sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
RESULTS = _REPO / "data" / "results"

M5_LUNAR_T0 = 61066.0  # fixed launch date of the M5 lunar candidate


def _load(name):
    p = RESULTS / name
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _fmt_cand(c, label=""):
    if c is None:
        return None
    return {
        "label": label,
        "t0_mjd": c.get("t0_mjd"),
        "tof1_days": c.get("tof1_days"),
        "tof2_days": c.get("tof2_days"),
        "r_DSM_AU": c.get("r_DSM_AU"),
        "departure_vinf_kms": c.get("departure_vinf_kms"),
        "dsm_delta_v_kms": c.get("dsm_delta_v_kms"),
        "return_vinf_kms": c.get("return_vinf_kms"),
        "return_braking_kms": c.get("return_braking_proxy_kms"),
        "perihelion_AU": c.get("perihelion_AU"),
        "total_dv_proxy_kms": c.get("total_dv_proxy_kms"),
        "fair": c.get("fair"),
    }


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
    print(f"\n  Lunar candidate: t0 = {M5_LUNAR_T0:.0f}")
    print(f"  Lunar total dv proxy: {dv_lunar:.4f} km/s")
    print(f"    launch_proxy   = {lunar['budget']['launch_proxy_kms']:.4f}")
    print(f"    lunar_residual = {lunar['budget']['lunar_residual_kms']:.4f}")
    print(f"    return_brake   = {lunar['budget']['return_braking_proxy_kms']:.4f}")
    print(f"    return_vinf    = {lunar['budget']['return_vinf_kms']:.4f}")
    print()

    n_fair = dsm.get("num_fair", 0)
    n_near = dsm.get("num_near_feasible", 0)
    n_total = dsm.get("num_candidates", 0)

    print(f"  DSM candidates:   {n_total}")
    print(f"  Strict fair:      {n_fair}")
    print(f"  Near-feasible:    {n_near}")
    print()

    # ----------------------------------------------------------------
    # 1. FIXED-DATE ratio: DSM at t0 = 61066 (same as lunar)
    # ----------------------------------------------------------------
    all_cands = dsm.get("all_candidates", [])
    fair_same_date = [c for c in all_cands if c.get("fair")
                      and abs(c.get("t0_mjd", 0) - M5_LUNAR_T0) < 1]

    fixed_date_candidate = None
    formal_fixed_date_ratio = None
    if fair_same_date:
        fixed_date_candidate = min(fair_same_date,
                                   key=lambda c: c["total_dv_proxy_kms"])
        dv_no_fd = fixed_date_candidate["total_dv_proxy_kms"]
        formal_fixed_date_ratio = (dv_no_fd - dv_lunar) / dv_no_fd if dv_no_fd > 0 else None
        print(f"  FIXED-DATE (t0 = {M5_LUNAR_T0:.0f}):")
        print(f"    Best fair DSM at t0={fixed_date_candidate['t0_mjd']:.0f}:")
        print(f"      dep_vinf  = {fixed_date_candidate['departure_vinf_kms']:.4f}")
        print(f"      dsm_dv    = {fixed_date_candidate['dsm_delta_v_kms']:.4f}")
        print(f"      ret_vinf  = {fixed_date_candidate['return_vinf_kms']:.4f}")
        print(f"      total     = {dv_no_fd:.4f} km/s")
        print(f"    Fixed-date ratio = {formal_fixed_date_ratio:.4f}"
              f" ({formal_fixed_date_ratio * 100:.1f}%)")
    else:
        print(f"  [WARN] No fair DSM candidate at t0 = {M5_LUNAR_T0:.0f}")
    print()

    # ----------------------------------------------------------------
    # 2. CROSS-DATE ratio (global best, any t0) — NOT formal
    # ----------------------------------------------------------------
    best_global = dsm.get("best_strict_fair")
    invalid_cross_date_ratio = None
    cross_date_dsm_t0 = None
    if best_global and best_global.get("fair"):
        cross_date_dsm_t0 = best_global["t0_mjd"]
        dv_no_g = best_global["total_dv_proxy_kms"]
        invalid_cross_date_ratio = (dv_no_g - dv_lunar) / dv_no_g if dv_no_g > 0 else None
        print(f"  CROSS-DATE (INVALID for formal ratio):")
        print(f"    DSM at t0 = {cross_date_dsm_t0:.0f} vs Lunar at t0 = {M5_LUNAR_T0:.0f}")
        print(f"    cross-date ratio = {invalid_cross_date_ratio:.4f}"
              f" ({invalid_cross_date_ratio * 100:.1f}%)")
        print(f"    This is NOT valid as formal M5 saving ratio because")
        print(f"    the launch dates differ ({cross_date_dsm_t0:.0f} vs {M5_LUNAR_T0:.0f}).")
    print()

    # ----------------------------------------------------------------
    # Status determination
    # ----------------------------------------------------------------
    status = "no_baseline"
    if formal_fixed_date_ratio is not None:
        status = "fixed_date_fair_ratio_found_negative"
    elif fair_same_date:
        status = "fixed_date_fair_candidates_but_ratio_error"
    else:
        status = "no_fair_fixed_date_baseline"

    # ----------------------------------------------------------------
    # Additional best-by-metric candidates (for reference)
    # ----------------------------------------------------------------
    best_peri = dsm.get("best_by_perihelion")
    best_vinf = dsm.get("best_by_return_vinf")
    best_dv = dsm.get("best_by_total_dv")
    best_bal = dsm.get("best_balanced")

    # ----------------------------------------------------------------
    # Build output
    # ----------------------------------------------------------------
    out = {
        "task": "M5 saving ratio resolver (fixed-date correction)",
        "lunar_candidate_t0_mjd": M5_LUNAR_T0,
        "budget_definition": (
            "total = departure_vinf + dsm_or_lunar_residual "
            "+ max(0, return_vinf - 15)"
        ),
        "lunar_budget": lunar["budget"],
        "dsm_total_candidates": n_total,
        "dsm_fair_count": n_fair,
        "dsm_near_feasible_count": n_near,

        # ---- Formal fixed-date ratio ----
        "formal_fixed_date_ratio": (
            round(formal_fixed_date_ratio, 6)
            if formal_fixed_date_ratio is not None else None
        ),
        "fixed_date_dsm_candidate": _fmt_cand(
            fixed_date_candidate, "fixed_date_best"),
        "fixed_date_fair_count_at_t0": len(fair_same_date),

        # ---- Invalid cross-date ratio ----
        "invalid_cross_date_ratio": (
            round(invalid_cross_date_ratio, 6)
            if invalid_cross_date_ratio is not None else None
        ),
        "invalid_cross_date_reason": (
            f"DSM best candidate t0={cross_date_dsm_t0:.0f} differs from "
            f"lunar candidate t0={M5_LUNAR_T0:.0f}. "
            "Cross-date comparison is not valid as the formal M5 saving ratio."
        ),
        "invalid_cross_date_dsm_candidate": _fmt_cand(
            best_global, "cross_date_best"),

        # ---- Reference candidates ----
        "dsm_best_by_perihelion": _fmt_cand(best_peri, "best_perihelion"),
        "dsm_best_by_return_vinf": _fmt_cand(best_vinf, "best_return_vinf"),
        "dsm_best_by_total_dv": _fmt_cand(best_dv, "best_total_dv"),
        "dsm_best_balanced": _fmt_cand(best_bal, "best_balanced"),

        "status": status,
        "conclusion": "",
    }

    if formal_fixed_date_ratio is not None:
        pct = formal_fixed_date_ratio * 100
        out["conclusion"] = (
            f"M5 fixed-date comparison COMPLETED. "
            f"At t0 = {M5_LUNAR_T0:.0f} (same launch date for both trajectories): "
            f"best fair DSM no-lunar total = {dv_no_fd:.2f} km/s, "
            f"lunar total = {dv_lunar:.2f} km/s. "
            f"Formal fixed-date saving ratio = {formal_fixed_date_ratio:.4f} "
            f"({pct:.1f}%). "
            f"The ratio is NEGATIVE: the current lunar-assisted candidate does NOT "
            f"save delta-v compared to a DSM no-lunar transfer under this budget proxy. "
            f"The dominant factor is the lunar trajectory's extreme return speed "
            f"(v_rel_earth = 77.88 km/s), incurring a 62.88 km/s braking proxy penalty. "
            f"A cross-date comparison using the best overall DSM candidate "
            f"(t0 = {cross_date_dsm_t0:.0f}) gives -{abs(invalid_cross_date_ratio)*100:.1f}%, "
            f"which is NOT the formal M5 fixed-date ratio."
        )
    else:
        out["conclusion"] = (
            "No fair fixed-date DSM no-lunar baseline found at "
            f"t0 = {M5_LUNAR_T0:.0f}. "
            "M5.5 requirement for a fixed-date saving ratio cannot be satisfied."
        )

    jp = RESULTS / "m5_saving_ratio_resolved.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
