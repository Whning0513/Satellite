"""
m5_fixed_date_lunar_vs_no_lunar_t61037.py
==========================================
Compare lunar best at t0=61037 with no-lunar baselines at same date.

Only computes formal ratio if both have valid Earth return at same t0.
"""
import json, os, sys
from pathlib import Path
_REPO = Path(__file__).resolve().parents[2]
RESULTS = _REPO / "data" / "results"

def _load(n):
    p = RESULTS / n
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

lunar = _load("m5_best_lunar_candidate_verify.json")
nl = _load("m5_fixed_date_no_lunar_t61037.json")

lunar_ok = lunar and lunar.get("event_check", {}).get("valid_return_event")
dsm_ok = nl and nl.get("dsm_no_lunar", {}).get("num_fair", 0) > 0
direct_ok = nl and nl.get("direct_lambert", {}).get("num_fair", 0) > 0

if lunar_ok and dsm_ok:
    best_nl = nl["dsm_no_lunar"]["best_fair"]
    lb = lunar["budget"]
    ratio_v = (best_nl["total"] - lb["total_dv_proxy_vinf_basis"]) / best_nl["total"]
    out = {"same_t0": True, "lunar_valid": True, "no_lunar_valid": True,
           "formal_ratio_vinf_basis": round(ratio_v, 6),
           "lunar_total_vinf": lb["total_dv_proxy_vinf_basis"],
           "no_lunar_total": best_nl["total"], "lunar_saves_delta_v": ratio_v > 0}
else:
    out = {"same_t0": True, "lunar_valid": lunar_ok,
           "no_lunar_valid": dsm_ok or direct_ok,
           "formal_ratio": None,
           "reason": f"lunar_valid={lunar_ok}, dsm_valid={dsm_ok}, direct_valid={direct_ok}",
           "no_lunar_note": (
               "No fair no-lunar DSM or direct candidate at t0=61037. "
               "Saving ratio cannot be computed as fixed-date comparison.")}

jp = RESULTS / "m5_fixed_date_lunar_vs_no_lunar_t61037.json"
with open(jp, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print(f"Saved: {jp}")
print(json.dumps(out, indent=2, ensure_ascii=False))
