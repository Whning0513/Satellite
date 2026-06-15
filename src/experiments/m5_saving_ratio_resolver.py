"""
m5_saving_ratio_resolver.py
============================
Resolves the M5 saving ratio.

PRIMARY source (if available):
  data/results/m5_fixed_date_current_compare.json
  This contains the active validated fixed-date comparison inside the
  formal 2026 launch window with verified Earth-return events for both
  lunar and no-lunar trajectories.

FALLBACK (if primary not available):
  Preserve the historical invalidated status rather than silently
  reviving old 61037-era comparisons.

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

    # ── PRIMARY: active 2026-window fixed-date comparison ──
    comp = _load("m5_fixed_date_current_compare.json")

    if comp and comp.get("formal_ratio_vinf_basis") is not None:
        ratio = comp["formal_ratio_vinf_basis"]
        lunar_total = comp["lunar_total_vinf_basis"]
        no_lunar_total = comp["no_lunar_dsm_total_vinf_basis"]
        lunar_ok = comp.get("lunar_valid", False)
        no_lunar_ok = comp.get("no_lunar_valid", False)
        same_t0 = float(comp.get("same_t0"))

        print(f"\n  [PRIMARY] Active fixed-date comparison (t0={same_t0}):")
        print(f"    lunar total: {lunar_total:.2f} km/s (valid={lunar_ok})")
        print(f"    no-lunar total: {no_lunar_total:.2f} km/s (valid={no_lunar_ok})")
        print(f"    saving ratio: {ratio:.6f} ({ratio*100:.1f}%)")
        print(f"    basis: vinf_basis (excess hyperbolic speed)")
        print(f"    same t0: {same_t0}")
        print(f"    same budget basis: {comp.get('same_budget_basis', True)}")
        print(f"    lunar saves delta_v: {ratio > 0}")

        out = {
            "task": "M5 saving ratio resolved",
            "status": "formal_fixed_date_positive_ratio",
            "primary_source": "m5_fixed_date_current_compare.json",
            "formal_fixed_date_ratio": round(ratio, 6),
            "formal_fixed_date_ratio_percent": round(ratio * 100, 1),
            "ratio_basis": "vinf_basis",
            "same_t0_mjd": same_t0,
            "same_budget_basis": bool(comp.get("same_budget_basis", True)),
            "lunar_total_vinf_basis_kms": round(lunar_total, 4),
            "lunar_valid_return_event": bool(lunar_ok),
            "no_lunar_total_vinf_basis_kms": round(no_lunar_total, 4),
            "no_lunar_valid_return_event": bool(no_lunar_ok),
            "lunar_saves_delta_v": ratio > 0,
            "classification": "ACTUAL_RESULT",
            # Historical invalid value — for reference only
            "invalid_historical_ratio_due_to_wrong_return_event": -1.873262,
            "invalid_historical_reason": (
                "Old lunar return_vinf=77.88 km/s was measured at perihelion "
                "from Earth (distance ~164 M km), not at Earth return. "
                "This historical value is NOT the formal fixed-date saving ratio."
            ),
        }
    else:
        print("\n  [FALLBACK] Active fixed-date comparison not available.")
        out = {
            "task": "M5 saving ratio resolved (fallback)",
            "status": "historical_anchor_invalidated",
            "formal_fixed_date_ratio": None,
            "same_budget_basis": False,
            "reason": (
                "The previous fixed-date anchor is no longer formal: either its launch date is outside the "
                "assignment window or its lunar side is not a valid Earth-return event after cache/trajectory fixes."
            ),
            "classification": "UNRESOLVED",
            "invalid_historical_ratio_due_to_wrong_return_event": -1.873262,
            "invalid_historical_positive_ratio_outside_window": 0.557881,
            "invalid_historical_reason": (
                "Old fixed-date formal results were tied to t0=61037 (2025-12-28), which is outside the assignment launch window; "
                "the repaired event-semantics check also no longer validates the lunar side as an Earth-return event."
            ),
        }

    # ── Save ──
    jp = RESULTS / "m5_saving_ratio_resolved.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
