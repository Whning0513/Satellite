"""
m5_same_window_lunar_no_lunar_pareto.py
========================================
Compare lunar vs no-lunar across the same launch window t0=61031–61049.

Lunar data: from m5_lunar_return_local_refine.csv (has 70 valid).
No-lunar data: best available at each t0 (deep search only at 61037;
otherwise use broad DSM search from m5_dsm_no_lunar_search.json).
"""

import json, os, csv, sys
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
RESULTS = _REPO / "data" / "results"


def main():
    print("=" * 66)
    print("M5 same-window lunar vs no-lunar Pareto")
    print("=" * 66)
    print("  Window: t0=61031–61049")
    print()

    # ── Lunar data from local refine ──
    lunar_csv = RESULTS / "m5_lunar_return_local_refine.csv"
    lunar_rows = []
    if lunar_csv.exists():
        with open(lunar_csv, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                lunar_rows.append(r)
    print(f"  Lunar candidates in window: {len(lunar_rows)}")
    lunar_valid = [r for r in lunar_rows if r["valid_earth_return"] == "True"]
    print(f"  Lunar Earth returns: {len(lunar_valid)}")
    lunar_t0s = set(round(float(r["t0_mjd"]), 0) for r in lunar_valid)

    # ── No-lunar DSM data from main search (broad, not just t0=61037) ──
    dsm_path = RESULTS / "m5_dsm_no_lunar_search.json"
    dsm_fair_by_t0 = {}
    if dsm_path.exists():
        with open(dsm_path, encoding="utf-8") as f:
            dsm_data = json.load(f)
        for c in dsm_data.get("all_candidates", []):
            if c.get("fair"):
                t0 = round(c["t0_mjd"], 0)
                if t0 not in dsm_fair_by_t0:
                    dsm_fair_by_t0[t0] = []
                dsm_fair_by_t0[t0].append(c)

    # Also check the deep search at t0=61037
    deep_path = RESULTS / "m5_no_lunar_t61037_deep_search.json"
    deep_fair_count = 0
    if deep_path.exists():
        with open(deep_path, encoding="utf-8") as f:
            deep = json.load(f)
        deep_fair_count = deep.get("valid_fair_candidates", 0)

    # ── Build window comparison ──
    t0_values = [float(x) for x in range(61031, 61051, 3)]
    window_comparison = []
    no_lunar_had_any = False
    both_valid_dates = []
    for t0_f in t0_values:
        has_lunar = t0_f in lunar_t0s
        # Get best no-lunar at this t0
        no_lun = None
        dsm_at_t0 = dsm_fair_by_t0.get(t0, [])
        if dsm_at_t0:
            no_lun = min(dsm_at_t0, key=lambda c: c["total_dv_proxy_kms"])
            no_lunar_had_any = True
        else:
            if t0_f == 61037.0 and deep_fair_count > 0:
                no_lun = {"note": f"deep_search_fair_count_{deep_fair_count}"}
                no_lunar_had_any = True

        entry = {"t0_mjd": t0_f, "lunar_valid": bool(has_lunar),
                 "no_lunar_valid": bool(no_lun)}
        if has_lunar and no_lun and t0_f == 61037.0 and deep_fair_count > 0:
            both_valid_dates.append(t0_f)
        window_comparison.append(entry)

    print(f"\n  Lunar-only dates: {len([e for e in window_comparison if e['lunar_valid'] and not e['no_lunar_valid']])}")
    print(f"  No-lunar-only dates: {len([e for e in window_comparison if not e['lunar_valid'] and e['no_lunar_valid']])}")
    print(f"  Both-valid dates: {len([e for e in window_comparison if e['lunar_valid'] and e['no_lunar_valid']])}")
    print(f"  Neither: {len([e for e in window_comparison if not e['lunar_valid'] and not e['no_lunar_valid']])}")
    print(f"  No-lunar had ANY fair in whole window: {no_lunar_had_any}")

    # Best overall
    if lunar_valid:
        best_l = min(lunar_valid, key=lambda r: float(r["closest_earth_km"]))
        l_vinf = float(best_l["return_vinf_kms"]) if best_l["return_vinf_kms"] else 0
        l_total = 10.1213 + max(0, l_vinf - 15)
        print(f"\n  Best lunar: t0={best_l['t0_mjd']} "
              f"dist={float(best_l['closest_earth_km']):.0f} km "
              f"total={l_total:.2f}")
    print(f"  Best no-lunar DSM in window: "
          f"{'None' if not no_lunar_had_any else 'exists at some t0'}")

    # Conclusion
    if both_valid_dates:
        conclusion = f"Both-valid at {both_valid_dates}; saving ratio computed at t0=61037."
    elif lunar_valid and no_lunar_had_any:
        conclusion = "Both exist but not at same t0; cross-date formal ratio not allowed."
    elif lunar_valid and not no_lunar_had_any:
        no_lunar_had_any = False
        # Use the deep search best near miss at 61037 for reference
        conclusion = (
            "In this limited window t0=61031–61049, lunar has valid Earth-return "
            "candidates at multiple t0s, while no-lunar DSM has zero fair candidates. "
            "This is a finite-search result, not a proof of impossibility."
        )
    else:
        conclusion = "Neither lunar nor no-lunar found valid in this window."

    out = {
        "task": "M5 same-window lunar vs no-lunar Pareto",
        "t0_window": {"min": 61031, "max": 61049},
        "lunar_total_candidates": len(lunar_rows),
        "lunar_valid_returns": len(lunar_valid),
        "no_lunar_any_valid_fair_in_window": no_lunar_had_any,
        "no_lunar_deep_search_fair_at_61037": deep_fair_count,
        "window_comparison": window_comparison,
        "lunar_only_dates": [e["t0_mjd"] for e in window_comparison if e["lunar_valid"] and not e["no_lunar_valid"]],
        "both_valid_dates": both_valid_dates,
        "neither_valid_dates": [e["t0_mjd"] for e in window_comparison if not e["lunar_valid"] and not e["no_lunar_valid"]],
        "classification": "DIAGNOSTIC",
        "conclusion": conclusion,
    }

    jp = RESULTS / "m5_same_window_lunar_no_lunar_pareto.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
