"""
m5_saving_ratio_resolver.py
============================
Resolves the M5 saving ratio from:
- m5_dsm_no_lunar_search.json (no-lunar DSM baseline)
- m5_lunar_budget_recomputed.json (lunar proxy budget)

CRITICAL UPDATE (2026-06-11): The M5 lunar trajectory does NOT reach Earth
return.  The S5 coast ends at perihelion (~0.28 AU, ~164 M km from Earth).
All lunar return_vinf / total_dv_proxy / saving ratio values derived from
the old 77.88 km/s "return_vinf" are INVALID because they compare a
heliocentric velocity difference at perihelion to an actual Earth-reentry
speed from the DSM no-lunar Lambert arrival.

This script now checks whether the lunar budget contains a valid
Earth-return event.  If not, no saving ratio is computed and the
status is set to "lunar_return_event_missing".

DSM no-lunar baselines remain valid individually but cannot be compared
to the incomplete lunar trajectory.

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
    print("M5 saving ratio resolver (return-event semantics)")
    print("=" * 66)

    dsm = _load("m5_dsm_no_lunar_search.json")
    lunar = _load("m5_lunar_budget_recomputed.json")

    if dsm is None:
        print("[ERROR] DSM no-lunar search results not found.")
        sys.exit(1)
    if lunar is None:
        print("[ERROR] Lunar budget recompute not found.")
        sys.exit(1)

    # ── Check lunar budget validity ──
    lunar_budget_valid = lunar.get("budget_valid", False)
    lunar_return_vinf = lunar.get("budget", {}).get("return_vinf_kms")
    dv_lunar = lunar.get("budget", {}).get("total_dv_proxy_kms")

    if lunar_budget_valid and dv_lunar is not None:
        print(f"\n  Lunar total dv proxy: {dv_lunar:.4f} km/s (VALID return)")
        lunar_ok = True
    else:
        print(f"\n  Lunar budget: INVALID — no Earth-return event")
        print(f"    return_vinf = {lunar_return_vinf}")
        if dv_lunar is not None:
            print(f"    old (invalid) total_dv = {dv_lunar:.4f}")
        lunar_ok = False

    # ── DSM no-lunar summary ──
    n_fair = dsm.get("num_fair", 0)
    n_near = dsm.get("num_near_feasible", 0)
    n_total = dsm.get("num_candidates", 0)
    print(f"\n  DSM candidates:   {n_total}")
    print(f"  Strict fair:      {n_fair}")
    print(f"  Near-feasible:    {n_near}")

    all_cands = dsm.get("all_candidates", [])
    fair_same_date = [c for c in all_cands if c.get("fair")
                      and abs(c.get("t0_mjd", 0) - 61066.0) < 1]

    # ── Best DSM candidates ──
    fixed_date_candidate = None
    if fair_same_date:
        fixed_date_candidate = min(fair_same_date,
                                   key=lambda c: c["total_dv_proxy_kms"])
        print(f"\n  Best DSM at t0=61066: "
              f"total={fixed_date_candidate['total_dv_proxy_kms']:.2f} km/s, "
              f"return_vinf={fixed_date_candidate['return_vinf_kms']:.2f} km/s")

    best_global = dsm.get("best_strict_fair")
    best_near = dsm.get("best_near_feasible")
    best_peri = dsm.get("best_by_perihelion")
    best_vinf = dsm.get("best_by_return_vinf")
    best_dv = dsm.get("best_by_total_dv")
    best_bal = dsm.get("best_balanced")

    # ── Status ──
    if not lunar_ok:
        status = "lunar_return_event_missing"
        conclusion = (
            "M5 lunar candidate has no validated Earth-return event. "
            "The trajectory ends at perihelion (~0.28 AU, ~164 M km from Earth). "
            "No formal saving ratio can be computed. "
            "DSM no-lunar baseline remains valid as an individual trajectory but "
            "cannot be compared to the incomplete lunar trajectory."
        )
        formal_fixed_date_ratio = None
    else:
        status = "lunar_return_valid_ratio_saved"
        # Compute ratio with proper return quantities
        dv_no_fd = fixed_date_candidate["total_dv_proxy_kms"] if fixed_date_candidate else 0
        formal_fixed_date_ratio = (dv_no_fd - dv_lunar) / dv_no_fd if dv_no_fd > 0 else None
        conclusion = (
            f"Lunar return event valid at 61066. "
            f"Fixed-date saving ratio = {formal_fixed_date_ratio:.4f}."
        )

    # ── Invalid cross-date ratio (for reference only) ──
    invalid_cross_date_ratio = None
    cross_date_dsm_t0 = None
    if best_global and best_global.get("fair"):
        cross_date_dsm_t0 = best_global["t0_mjd"]
        dv_no_g = best_global["total_dv_proxy_kms"]
        invalid_cross_date_ratio = (dv_no_g - 0) / dv_no_g if dv_no_g > 0 else None

    # ── Build output ──
    out = {
        "task": "M5 saving ratio resolver (return-event semantics)",
        "lunar_return_event_valid": lunar_ok,
        "lunar_return_vinf_valid": lunar_budget_valid,
        "lunar_candidate_t0_mjd": 61066.0,
        "dsm_total_candidates": n_total,
        "dsm_fair_count": n_fair,
        "dsm_near_feasible_count": n_near,
        "fixed_date_fair_count_at_t0": len(fair_same_date),
        "fixed_date_dsm_candidate": _fmt_cand(
            fixed_date_candidate, "fixed_date_best"),
        "formal_fixed_date_ratio": (
            round(formal_fixed_date_ratio, 6)
            if formal_fixed_date_ratio is not None else None),
        "invalid_cross_date_ratio": (
            round(invalid_cross_date_ratio, 6)
            if invalid_cross_date_ratio is not None else None),
        "invalid_cross_date_reason": (
            f"Cross-date ratio invalid because lunar return event missing."
        ),
        # Keep historical invalid ratio for reference
        "invalid_ratio_due_to_lunar_return_event": None,
        "invalid_ratio_reason": (
            "lunar return_vinf was measured at perihelion (~0.28 AU), "
            "not at Earth return. All lunar return quantities nulled."
        ),
        "dsm_best_by_perihelion": _fmt_cand(best_peri, "best_perihelion"),
        "dsm_best_by_return_vinf": _fmt_cand(best_vinf, "best_return_vinf"),
        "dsm_best_by_total_dv": _fmt_cand(best_dv, "best_total_dv"),
        "dsm_best_balanced": _fmt_cand(best_bal, "best_balanced"),
        "status": status,
        "conclusion": conclusion,
    }

    jp = RESULTS / "m5_saving_ratio_resolved.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n  Status: {status}")
    print(f"  Formal saving ratio: {formal_fixed_date_ratio}")
    print(f"\nSaved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
