"""
m5_saving_ratio_resolver.py
============================
Resolves the M5 saving ratio from:
- m5_dsm_no_lunar_search.json (no-lunar DSM baseline)
- m5_lunar_budget_recomputed.json (lunar proxy budget)
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
        print("[ERROR] DSM no-lunar search results not found. Run repair-m5-real first.")
        sys.exit(1)
    if lunar is None:
        print("[ERROR] Lunar budget recompute not found. Run repair-m5-real first.")
        sys.exit(1)

    dv_lunar = lunar["budget"]["total_dv_proxy_kms"]
    print(f"\n  Lunar total dv proxy: {dv_lunar:.3f} km/s")

    # Best strict fair baseline
    bc = dsm.get("best_candidate")
    fair = [bc] if bc and bc.get("fair") else []
    near = [bc] if bc and bc.get("near_feasible") else []
    # Actually candidates are in lists, let me read from the right fields
    # The summary has best_candidate (single) but num_fair etc
    # Let me get candidates from the raw data (this script reads JSON output)
    # The JSON has num_fair/num_near_feasible but not the full list

    n_fair = dsm.get("num_fair", 0)
    n_near = dsm.get("num_near_feasible", 0)
    n_total = dsm.get("num_candidates", 0)

    print(f"  DSM candidates: {n_total}, fair: {n_fair}, near-feasible: {n_near}")

    formal_saving_ratio = None
    reference_ratio = None
    status = "no_baseline"

    # Best candidate
    best = dsm.get("best_candidate")
    best_near = dsm.get("best_near_feasible")

    if best and best.get("fair"):
        dv_no = best["total_dv_proxy_kms"]
        formal_saving_ratio = (dv_no - dv_lunar) / dv_no if dv_no > 0 else 0
        status = "strict_fair_saving_ratio_found"
        print(f"\n  STRICT FAIR: dv_no_lunar={dv_no:.3f}, ratio={formal_saving_ratio:.4f}")
    elif best_near:
        dv_no = best_near["total_dv_proxy_kms"]
        reference_ratio = (dv_no - dv_lunar) / dv_no if dv_no > 0 else 0
        status = "near_feasible_reference_only"
        print(f"\n  NEAR-FEASIBLE: dv_no_lunar={dv_no:.3f}, "
              f"ref_ratio={reference_ratio:.4f}")
        print("  NOT valid as formal saving ratio.")
    else:
        print(f"\n  No fair or near-feasible baseline found.")
        if best:
            dv_no = best["total_dv_proxy_kms"]
            print(f"  Best invalid: dv_no_lunar={dv_no:.3f}")
        status = "no_fair_or_near_feasible_baseline"

    # Output
    out = {
        "task": "M5 saving ratio resolver",
        "lunar_total_dv_proxy_kms": dv_lunar,
        "dsm_total_candidates": n_total,
        "dsm_fair_count": n_fair,
        "dsm_near_feasible_count": n_near,
        "dsm_best_candidate": best,
        "dsm_best_near_feasible": best_near,
        "formal_saving_ratio": round(formal_saving_ratio, 4) if formal_saving_ratio is not None else None,
        "reference_saving_ratio": round(reference_ratio, 4) if reference_ratio is not None else None,
        "status": status,
        "conclusion": (
            f"Strict fair baseline {'FOUND' if formal_saving_ratio else 'NOT FOUND'}. "
            f"Near-feasible: {'FOUND (REFERENCE ONLY)' if reference_ratio else 'NOT FOUND'}. "
            f"M5 saving ratio requirement: "
            f"{'CAN be satisfied' if formal_saving_ratio else 'cannot be satisfied with current search'}."
        ),
    }

    jp = RESULTS / "m5_saving_ratio_resolved.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
