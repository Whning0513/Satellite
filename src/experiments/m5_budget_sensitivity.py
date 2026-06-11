"""
m5_budget_sensitivity.py
=========================
Budget sensitivity analysis for the M5 lunar vs no-lunar comparison.

Three budget modes are evaluated at the FIXED-DATE t0 = MJD 61066:

Mode A: Threshold-excess braking (baseline)
  total = departure_vinf + residual + max(0, return_vinf - 15)

Mode B: Full return-vinf braking
  total = departure_vinf + residual + return_vinf
  (assumes all return speed must be braked)

Mode C: Entry-speed proxy
  entry_speed = sqrt(return_vinf^2 + V_ESC_EARTH^2)
  total = departure_vinf + residual + max(0, entry_speed - 15)
  (uses atmospheric-entry speed threshold)

If saving_ratio < 0 in all modes, the conclusion that the current lunar
candidate does NOT save Δv under uniform proxy is robust.

Output: data/results/m5_budget_sensitivity.json
"""

import json, os, sys, math
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

RESULTS = _REPO / "data" / "results"
from constants import V_ESCAPE_EARTH

M5_LUNAR_T0 = 61066.0
V_RET_THRESHOLD = 15.0


def _load(name):
    p = RESULTS / name
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _saving_ratio(dv_no, dv_lu):
    if dv_no is None or dv_lu is None or dv_no <= 0:
        return None
    return (dv_no - dv_lu) / dv_no


def main():
    print("=" * 66)
    print("M5 budget sensitivity analysis")
    print("=" * 66)

    dsm = _load("m5_dsm_no_lunar_search.json")
    lunar = _load("m5_lunar_budget_recomputed.json")
    if dsm is None or lunar is None:
        print("[ERROR] Results not found. Run repair-m5-real first.")
        sys.exit(1)

    # ---- Fixed-date DSM candidate at t0=61066 ----
    all_cands = dsm.get("all_candidates", [])
    fair_same = [c for c in all_cands if c.get("fair")
                 and abs(c.get("t0_mjd", 0) - M5_LUNAR_T0) < 1]
    if not fair_same:
        print(f"[ERROR] No fair DSM candidate at t0={M5_LUNAR_T0:.0f}")
        sys.exit(1)

    best = min(fair_same, key=lambda c: c["total_dv_proxy_kms"])

    lunar_residual = 0.0  # gravity assist, free
    dsm_residual = best["dsm_delta_v_kms"]

    dep_lunar = lunar["budget"]["departure_vinf_kms"]
    ret_lunar = lunar["budget"]["return_vinf_kms"]  # may be None
    dep_dsm = best["departure_vinf_kms"]
    ret_dsm = best["return_vinf_kms"]

    # Check if lunar budget is valid
    lunar_budget_valid = lunar.get("budget_valid", False)

    if not lunar_budget_valid or ret_lunar is None:
        print("\n  [SKIP] Lunar budget invalid — no Earth-return event.")
        print("  Budget sensitivity cannot be computed with lunar at perihelion.")
        out = {
            "task": "M5 budget sensitivity (INVALIDATED — lunar return missing)",
            "lunar_return_event_valid": False,
            "note": "Lunar trajectory has no Earth return. Cannot compute sensitivity.",
            }
        jp = RESULTS / "m5_budget_sensitivity.json"
        with open(jp, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        print(f"\nSaved: {jp}")
        return

    modes = {}

    # ---- Mode A: threshold-excess braking ----
    lu_a = dep_lunar + lunar_residual + max(0, ret_lunar - V_RET_THRESHOLD)
    no_a = dep_dsm + dsm_residual + max(0, ret_dsm - V_RET_THRESHOLD)
    ratio_a = _saving_ratio(no_a, lu_a)
    modes["A_threshold_braking"] = {
        "description": "total = departure_vinf + residual + max(0, return_vinf - 15)",
        "lunar_departure_vinf": round(dep_lunar, 4),
        "lunar_residual": round(lunar_residual, 4),
        "lunar_return_vinf": round(ret_lunar, 4),
        "lunar_braking_proxy": round(max(0, ret_lunar - V_RET_THRESHOLD), 4),
        "lunar_total": round(lu_a, 4),
        "no_lunar_departure_vinf": round(dep_dsm, 4),
        "no_lunar_dsm_delta_v": round(dsm_residual, 4),
        "no_lunar_return_vinf": round(ret_dsm, 4),
        "no_lunar_braking_proxy": round(max(0, ret_dsm - V_RET_THRESHOLD), 4),
        "no_lunar_total": round(no_a, 4),
        "saving_ratio": round(ratio_a, 6) if ratio_a is not None else None,
        "lunar_saves_delta_v": bool(ratio_a is not None and ratio_a > 0),
    }
    print(f"\nMode A (threshold-excess braking):")
    print(f"  Lunar:  {lu_a:.4f} = {dep_lunar:.4f} + 0 + max(0, {ret_lunar:.4f} - 15)")
    print(f"  No-lun: {no_a:.4f} = {dep_dsm:.4f} + {dsm_residual:.4f} + max(0, {ret_dsm:.4f} - 15)")
    print(f"  Ratio:  {ratio_a:.4f} ({ratio_a*100:.1f}%)")
    print(f"  Lunar saves Δv: {ratio_a > 0}")

    # ---- Mode B: full return-vinf braking ----
    lu_b = dep_lunar + lunar_residual + ret_lunar
    no_b = dep_dsm + dsm_residual + ret_dsm
    ratio_b = _saving_ratio(no_b, lu_b)
    modes["B_full_return_vinf_braking"] = {
        "description": "total = departure_vinf + residual + return_vinf",
        "lunar_total": round(lu_b, 4),
        "no_lunar_total": round(no_b, 4),
        "saving_ratio": round(ratio_b, 6) if ratio_b is not None else None,
        "lunar_saves_delta_v": bool(ratio_b is not None and ratio_b > 0),
    }
    print(f"\nMode B (full return-vinf braking):")
    print(f"  Lunar:  {lu_b:.4f} = {dep_lunar:.4f} + 0 + {ret_lunar:.4f}")
    print(f"  No-lun: {no_b:.4f} = {dep_dsm:.4f} + {dsm_residual:.4f} + {ret_dsm:.4f}")
    print(f"  Ratio:  {ratio_b:.4f} ({ratio_b*100:.1f}%)")
    print(f"  Lunar saves Δv: {ratio_b > 0}")

    # ---- Mode C: entry-speed proxy ----
    entry_lunar = math.sqrt(ret_lunar**2 + V_ESCAPE_EARTH**2)
    entry_dsm = math.sqrt(ret_dsm**2 + V_ESCAPE_EARTH**2)
    lu_c = dep_lunar + lunar_residual + max(0, entry_lunar - V_RET_THRESHOLD)
    no_c = dep_dsm + dsm_residual + max(0, entry_dsm - V_RET_THRESHOLD)
    ratio_c = _saving_ratio(no_c, lu_c)
    modes["C_entry_speed_proxy"] = {
        "description": (
            "total = departure_vinf + residual + max(0, entry_speed - 15); "
            "entry_speed = sqrt(return_vinf^2 + V_esc^2)"
        ),
        "lunar_entry_speed": round(entry_lunar, 4),
        "lunar_total": round(lu_c, 4),
        "no_lunar_entry_speed": round(entry_dsm, 4),
        "no_lunar_total": round(no_c, 4),
        "saving_ratio": round(ratio_c, 6) if ratio_c is not None else None,
        "lunar_saves_delta_v": bool(ratio_c is not None and ratio_c > 0),
    }
    print(f"\nMode C (entry-speed proxy):")
    print(f"  entry_lunar = sqrt({ret_lunar:.4f}^2 + {V_ESCAPE_EARTH:.2f}^2) = {entry_lunar:.4f}")
    print(f"  entry_dsm   = sqrt({ret_dsm:.4f}^2 + {V_ESCAPE_EARTH:.2f}^2) = {entry_dsm:.4f}")
    print(f"  Lunar:  {lu_c:.4f} = {dep_lunar:.4f} + 0 + max(0, {entry_lunar:.4f} - 15)")
    print(f"  No-lun: {no_c:.4f} = {dep_dsm:.4f} + {dsm_residual:.4f} + max(0, {entry_dsm:.4f} - 15)")
    print(f"  Ratio:  {ratio_c:.4f} ({ratio_c*100:.1f}%)")
    print(f"  Lunar saves Δv: {ratio_c > 0}")

    # ---- Consistency check ----
    all_negative = all(
        modes[m].get("saving_ratio") is not None and modes[m]["saving_ratio"] < 0
        for m in modes)
    all_positive = all(
        modes[m].get("saving_ratio") is not None and modes[m]["saving_ratio"] > 0
        for m in modes)
    mixed = not all_negative and not all_positive

    if all_negative:
        robustness = (
            "All budget modes give negative saving ratios. "
            "Conclusion robust: the current lunar-assisted candidate does not "
            "save delta-v under any reasonable uniform proxy."
        )
    elif mixed:
        robustness = (
            "Budget modes give mixed saving ratios. "
            "The fixed-date comparison outcome depends on the budget proxy choice."
        )
    else:
        robustness = (
            "All budget modes give positive saving ratios. "
            "The lunar-assisted candidate saves delta-v consistently."
        )

    print(f"\n  Robustness: {robustness}")

    # ---- Save ----
    out = {
        "task": "M5 budget sensitivity (fixed-date, t0=61066)",
        "lunar_candidate":
            _fmt_cand({"departure_vinf_kms": dep_lunar,
                       "return_vinf_kms": ret_lunar,
                       "lunar_residual_kms": lunar_residual, "t0_mjd": M5_LUNAR_T0}),
        "no_lunar_dsm_candidate":
            _fmt_cand(best),
        "budget_modes": modes,
        "all_modes_negative": all_negative,
        "all_modes_positive": all_positive,
        "mixed_sign": mixed,
        "robustness_conclusion": robustness,
    }

    jp = RESULTS / "m5_budget_sensitivity.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")
    print("=" * 66)


def _fmt_cand(c):
    return {
        "t0_mjd": c.get("t0_mjd"),
        "departure_vinf_kms": c.get("departure_vinf_kms"),
        "dsm_delta_v_kms": c.get("dsm_delta_v_kms"),
        "return_vinf_kms": c.get("return_vinf_kms"),
        "total_dv_proxy_kms": c.get("total_dv_proxy_kms"),
        "lunar_residual_kms": c.get("lunar_residual_kms", 0.0),
    }


if __name__ == "__main__":
    main()
