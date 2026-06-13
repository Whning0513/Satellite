"""
m5_t61037_lunar_vs_no_lunar_deep_compare.py
============================================
Compare lunar best at t0=61037 with deepened no-lunar DSM at same date.
"""

import json, sys
from pathlib import Path
_REPO = Path(__file__).resolve().parents[2]
RESULTS = _REPO / "data" / "results"
sys.path.insert(0, str(_REPO / "src"))
from mission_constraints import is_launch_mjd_in_window, mjd_to_date_str

def _load(n):
    p = RESULTS / n
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

lunar = _load("m5_best_lunar_candidate_verify.json")
nl = _load("m5_no_lunar_t61037_deep_search.json")

lunar_ok = lunar and lunar.get("event_check", {}).get("valid_return_event")
nl_fair = nl.get("valid_fair_candidates", 0) if nl else 0
nl_best = nl.get("best_valid") if nl else None
t0 = 61037
t0_in_window = is_launch_mjd_in_window(t0)

if lunar_ok and nl_fair > 0 and nl_best and t0_in_window:
    lb = lunar["budget"]
    nl_total = nl_best["total_dv_proxy_kms"]
    ratio_v = (nl_total - lb["total_dv_proxy_vinf_basis"]) / nl_total
    le = lb["total_dv_proxy_launch_equivalent_basis"]

    out = {
        "same_t0": 61037,
        "lunar_valid": True, "no_lunar_valid": True,
        "same_budget_basis": True,
        "budget_basis": "vinf_basis",
        "formal_ratio_vinf_basis": round(ratio_v, 6),
        "lunar_total_vinf_basis": lb["total_dv_proxy_vinf_basis"],
        "lunar_total_launch_equivalent": le,
        "no_lunar_dsm_total_vinf_basis": nl_total,
        "no_lunar_dsm_delta_v": nl_best["dsm_delta_v_kms"],
        "no_lunar_dsm_return_vinf": nl_best["return_vinf_kms"],
        "lunar_saves_delta_v_vinf_basis": ratio_v > 0,
        "launch_window_valid": True,
        "same_t0_date": mjd_to_date_str(t0),
        "classification": "ACTUAL_RESULT",
    }
else:
    lunar_vinf = lunar["budget"]["total_dv_proxy_vinf_basis"] if lunar else "N/A"
    out = {
        "same_t0": t0,
        "same_t0_date": mjd_to_date_str(t0),
        "lunar_valid": bool(lunar_ok),
        "no_lunar_valid": nl_fair > 0,
        "same_budget_basis": True,
        "budget_basis": "vinf_basis",
        "formal_ratio_vinf_basis": None,
        "lunar_total_vinf_basis": lunar_vinf,
        "no_lunar_fair_count": nl_fair,
        "no_lunar_note": nl.get("status", "unknown") if nl else "file missing",
        "launch_window_valid": t0_in_window,
        "classification": "INVALID_FORMAL_WINDOW_OR_EVENT",
        "reason": (
            f"launch_window_valid={t0_in_window}, lunar_valid={lunar_ok}, "
            f"no_lunar_fair={nl_fair}. Cannot compute formal same-date ratio."
        ),
    }

jp = RESULTS / "m5_t61037_lunar_vs_no_lunar_deep_compare.json"
with open(jp, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print(f"Saved: {jp}")
print(json.dumps(out, indent=2, ensure_ascii=False))
