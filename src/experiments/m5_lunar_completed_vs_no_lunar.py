"""
m5_lunar_completed_vs_no_lunar.py
==================================
Compares the completed M5 lunar trajectory (with return DSM) to the
DSM no-lunar baseline at the same launch date.

Output: data/results/m5_lunar_completed_comparison.json
"""

import json, os, sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
RESULTS = _REPO / "data" / "results"


def main():
    print("=" * 66)
    print("M5 lunar completed vs no-lunar comparison")
    print("=" * 66)

    comp_path = RESULTS / "m5_lunar_return_completion.json"
    dsm_path = RESULTS / "m5_dsm_no_lunar_search.json"

    if not comp_path.exists() or not dsm_path.exists():
        print("[ERROR] Run m5_lunar_return_completion.py and m5_dsm_no_lunar_search.py first.")
        sys.exit(1)

    with open(comp_path, "r", encoding="utf-8") as f:
        comp = json.load(f)
    with open(dsm_path, "r", encoding="utf-8") as f:
        dsm = json.load(f)

    # Get best DSM at t0=61066
    dsm_cands = [c for c in dsm.get("all_candidates", [])
                 if c.get("fair") and abs(c.get("t0_mjd", 0) - 61066.0) < 1]
    dsm_best = min(dsm_cands, key=lambda c: c["total_dv_proxy_kms"]) if dsm_cands else None

    # Pure lunar
    pure = comp["pure_lunar_free_return"]
    print(f"\nPure lunar free return:")
    print(f"  Status: {pure['status']}")

    # Completed lunar
    completed = comp["lunar_plus_return_dsm"]
    print(f"\nLunar + return DSM:")
    print(f"  Status: {completed['status']}")
    print(f"  Fair candidates: {completed['num_fair']}")

    if completed.get("best_fair") and dsm_best:
        lb = completed["best_fair"]
        db = dsm_best
        lunar_total = lb["total_dv_proxy_kms"]
        dsm_total = db["total_dv_proxy_kms"]
        ratio = (dsm_total - lunar_total) / dsm_total if dsm_total > 0 else None

        print(f"\nComparison (lunar completed vs no-lunar DSM):")
        print(f"  Lunar completed total: {lunar_total:.2f} km/s")
        print(f"  DSM no-lunar total:    {dsm_total:.2f} km/s")
        print(f"  Reference ratio: {ratio:.4f} ({ratio*100:.1f}%)")
        print(f"  Mission class: lunar_plus_return_dsm_vs_no_lunar_dsm")
        print(f"  NOT equivalent to pure lunar saving ratio")

        comparison = {
            "lunar_completed_total_kms": lunar_total,
            "lunar_return_dsm_kms": lb["return_dsm_kms"],
            "lunar_arrival_vinf_kms": lb["arrival_return_vinf_kms"],
            "no_lunar_dsm_total_kms": dsm_total,
            "reference_saving_ratio": round(ratio, 6),
            "mission_class": "lunar_plus_return_dsm_vs_no_lunar_dsm",
            "not_equivalent_to_pure_lunar_saving": True,
        }
    else:
        comparison = None
        print("\n  Cannot compare: missing data")

    out = {
        "task": "M5 lunar completed vs no-lunar",
        "pure_lunar_free_return": pure,
        "lunar_completed": completed.get("best_fair") if completed.get("best_fair") else None,
        "dsm_no_lunar_best_at_t0_61066": dsm_best,
        "comparison": comparison,
        "conclusion": (
            "Pure lunar free return: MISSING. "
            "Lunar+return-DSM completed comparison available as reference only."
        ),
    }

    jp = RESULTS / "m5_lunar_completed_comparison.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
