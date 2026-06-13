"""
m5_fixed_date_current_compare.py
================================
Formal same-date lunar vs no-lunar comparison at the current legal M5 anchor.
"""

from __future__ import annotations

import json
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
RESULTS = _REPO / "data" / "results"

VERIFY = RESULTS / "m5_best_lunar_candidate_verify.json"
NO_LUNAR = RESULTS / "m5_no_lunar_fixed_date_deep_search.json"


def main() -> int:
    lunar = json.loads(VERIFY.read_text(encoding="utf-8"))
    no_lunar = json.loads(NO_LUNAR.read_text(encoding="utf-8"))

    t0 = float(lunar["candidate"]["t0_mjd"])
    budget = lunar["budget"]
    best = no_lunar.get("best_valid")
    lunar_ok = bool(lunar["event_check"]["valid_return_event"] and lunar["candidate"]["launch_window_valid"])
    no_lunar_ok = best is not None and bool(no_lunar.get("launch_window_valid"))

    if lunar_ok and no_lunar_ok:
        lunar_total = float(budget["total_dv_proxy_vinf_basis"])
        no_lunar_total = float(best["total_dv_proxy_kms"])
        ratio = (no_lunar_total - lunar_total) / no_lunar_total
        out = {
            "same_t0": t0,
            "same_t0_date": lunar["candidate"]["t0_date"],
            "launch_window_valid": True,
            "lunar_valid": True,
            "no_lunar_valid": True,
            "same_budget_basis": True,
            "budget_basis": "vinf_basis",
            "formal_ratio_vinf_basis": round(ratio, 6),
            "lunar_total_vinf_basis": round(lunar_total, 4),
            "lunar_total_launch_equivalent": float(budget["total_dv_proxy_launch_equivalent_basis"]),
            "no_lunar_dsm_total_vinf_basis": round(no_lunar_total, 4),
            "no_lunar_dsm_delta_v": float(best["dsm_delta_v_kms"]),
            "no_lunar_dsm_return_vinf": float(best["return_vinf_kms"]),
            "lunar_saves_delta_v_vinf_basis": ratio > 0,
            "classification": "ACTUAL_RESULT",
        }
    else:
        out = {
            "same_t0": t0,
            "same_t0_date": lunar["candidate"]["t0_date"],
            "launch_window_valid": bool(lunar["candidate"]["launch_window_valid"]),
            "lunar_valid": lunar_ok,
            "no_lunar_valid": no_lunar_ok,
            "same_budget_basis": True,
            "budget_basis": "vinf_basis",
            "formal_ratio_vinf_basis": None,
            "reason": f"lunar_valid={lunar_ok}, no_lunar_valid={no_lunar_ok}",
            "classification": "UNRESOLVED",
        }

    out_path = RESULTS / "m5_fixed_date_current_compare.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved: {out_path}")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
