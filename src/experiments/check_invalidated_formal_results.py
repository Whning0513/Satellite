"""Checks active JSON results for invalidated lunar return values."""
import json, sys, os
from pathlib import Path
_REPO = Path(__file__).resolve().parents[2]
RESULTS = _REPO / "data" / "results"
ERRORS = []

def check(fp):
    if not fp.exists(): return
    d = json.loads(fp.read_text(encoding="utf-8"))
    n = fp.name

    if n == "m5_saving_ratio_resolved.json":
        status = d.get("status", "")
        # Accept either positive ratio or documented null
        if status == "formal_fixed_date_positive_ratio":
            # Check that ratio is actually present and positive
            ratio = d.get("formal_fixed_date_ratio")
            if ratio is None:
                ERRORS.append(f"[FAIL] {n}: status=positive_ratio but ratio is None")
            elif ratio < 0:
                ERRORS.append(f"[FAIL] {n}: status=positive_ratio but ratio={ratio} < 0")
            elif abs(ratio + 1.873) < 0.01:
                ERRORS.append(f"[FAIL] {n}: ratio={ratio} matches old invalid -1.873")
        elif status == "lunar_return_event_missing":
            # Legacy/fallback: ratio must be None
            if d.get("formal_fixed_date_ratio") is not None:
                ERRORS.append(f"[FAIL] {n}: status=missing but ratio is not None")
        else:
            ERRORS.append(f"[FAIL] {n}: unknown status '{status}'")

    if n == "m5_lunar_budget_recomputed.json":
        if d.get("budget_valid", True) == True:
            ERRORS.append(f"[FAIL] {n}: budget_valid should be False")
        if d.get("budget", {}).get("total_dv_proxy_kms") is not None:
            ERRORS.append(f"[FAIL] {n}: total_dv_proxy_kms must be None")

    if n == "m5_budget_sensitivity.json":
        if d.get("lunar_return_event_valid", True) == True:
            ERRORS.append(f"[FAIL] {n}: lunar_return_event_valid should be False")

    if n == "m6_actual_constrained_search.json":
        for c in d.get("mode_a_actual_trajectory", []):
            if c.get("return_vinf_kms") and abs(c["return_vinf_kms"] - 77.88) < 0.1:
                # Only flag if not guarded by event_valid=False
                event_valid = c.get("return_vinf_event_valid")
                allow = (event_valid is False)  # explicitly marked invalid
                if not allow:
                    ERRORS.append(
                        f"[FAIL] {n}: t0={c['t0_mjd']} return_vinf_kms={c['return_vinf_kms']} "
                        f"(invalid perihelion-measured)")

    if n == "m5_lunar_return_completion.json":
        pure = d.get("pure_lunar_free_return", {})
        if pure.get("valid_earth_return_found", True) == True:
            ERRORS.append(f"[FAIL] {n}: pure_lunar_free_return should have valid_earth_return_found=False")
        comp = d.get("lunar_plus_return_dsm", {})
        status = comp.get("status", "")
        if status not in ("completed", "no_candidate"):
            ERRORS.append(f"[FAIL] {n}: lunar_plus_return_dsm status should be completed or no_candidate")

    if n == "m6_lunar_return_completion.json":
        if d.get("classification") == "ACTUAL_RESULT":
            ERRORS.append(f"[FAIL] {n}: classification should be FINITE_SEARCH_NEG")
        if d.get("num_pure_returns", -1) != 0:
            ERRORS.append(f"[FAIL] {n}: num_pure_returns should be 0")

for jp in sorted(Path(RESULTS).glob("*.json")):
    check(jp)

if ERRORS:
    for e in ERRORS:
        print(e)
    print(f"\n{len(ERRORS)} failure(s)")
    sys.exit(1)
else:
    print("OK: No forbidden formal values in active result files.")
    sys.exit(0)
