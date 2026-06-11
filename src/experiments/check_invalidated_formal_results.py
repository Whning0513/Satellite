"""Checks active JSON results for invalidated lunar return values."""
import json, sys
from pathlib import Path
_REPO = Path(__file__).resolve().parents[2]
RESULTS = _REPO / "data" / "results"
ERRORS = []


def _near(value, target, tol):
    return value is not None and abs(value - target) <= tol

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
            elif _near(ratio, -1.873262, 1e-6):
                ERRORS.append(f"[FAIL] {n}: ratio={ratio} matches old invalid -1.873")
            elif not _near(ratio, 0.557881, 1e-6):
                ERRORS.append(f"[FAIL] {n}: positive ratio expected 0.557881, got {ratio}")
            if d.get("same_t0_mjd") != 61037.0:
                ERRORS.append(f"[FAIL] {n}: same_t0_mjd must be 61037.0")
            if d.get("same_budget_basis") is not True:
                ERRORS.append(f"[FAIL] {n}: same_budget_basis must be true")
            if d.get("ratio_basis") != "vinf_basis":
                ERRORS.append(f"[FAIL] {n}: ratio_basis must be vinf_basis")
            if d.get("lunar_valid_return_event") is not True:
                ERRORS.append(f"[FAIL] {n}: lunar_valid_return_event must be true")
            if d.get("no_lunar_valid_return_event") is not True:
                ERRORS.append(f"[FAIL] {n}: no_lunar_valid_return_event must be true")
            if d.get("classification") != "ACTUAL_RESULT":
                ERRORS.append(f"[FAIL] {n}: classification must be ACTUAL_RESULT")
        elif status == "lunar_return_event_missing":
            # Legacy/fallback: ratio must be None
            if d.get("formal_fixed_date_ratio") is not None:
                ERRORS.append(f"[FAIL] {n}: status=missing but ratio is not None")
        else:
            ERRORS.append(f"[FAIL] {n}: unknown status '{status}'")

    if n == "m5_t61037_lunar_vs_no_lunar_deep_compare.json":
        ratio = d.get("formal_ratio_vinf_basis")
        if ratio is None:
            ERRORS.append(f"[FAIL] {n}: compare JSON missing formal_ratio_vinf_basis")
        elif not _near(ratio, 0.557881, 1e-6):
            ERRORS.append(f"[FAIL] {n}: compare ratio expected 0.557881, got {ratio}")
        if d.get("same_t0") != 61037:
            ERRORS.append(f"[FAIL] {n}: same_t0 must be 61037")
        if d.get("same_budget_basis") is not True:
            ERRORS.append(f"[FAIL] {n}: same_budget_basis must be true")
        if d.get("budget_basis") != "vinf_basis":
            ERRORS.append(f"[FAIL] {n}: budget_basis must be vinf_basis")
        if d.get("lunar_valid") is not True:
            ERRORS.append(f"[FAIL] {n}: lunar_valid must be true")
        if d.get("no_lunar_valid") is not True:
            ERRORS.append(f"[FAIL] {n}: no_lunar_valid must be true")

    if n == "m5_best_lunar_candidate_verify.json":
        event_check = d.get("event_check", {})
        state = d.get("state_at_return", {})
        budget = d.get("budget", {})
        if event_check.get("valid_return_event") is not True:
            ERRORS.append(f"[FAIL] {n}: valid_return_event must be true")
        if event_check.get("event_type") != "earth_return":
            ERRORS.append(f"[FAIL] {n}: event_type must be earth_return")
        if state.get("return_vinf_kms") is None:
            ERRORS.append(f"[FAIL] {n}: return_vinf_kms missing at Earth-return event")
        if budget.get("return_vinf_kms") is None:
            ERRORS.append(f"[FAIL] {n}: budget.return_vinf_kms missing at Earth-return event")
        if _near(state.get("return_vinf_kms"), 77.88, 0.1) or _near(budget.get("return_vinf_kms"), 77.88, 0.1):
            ERRORS.append(f"[FAIL] {n}: old invalid 77.88 km/s return_vinf leaked into formal Earth-return result")
        if _near(budget.get("total_dv_proxy_vinf_basis"), 73.0, 0.2):
            ERRORS.append(f"[FAIL] {n}: old invalid lunar total ~73 km/s leaked into formal result")

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

    if n == "m5_no_lunar_t61037_deep_search.json":
        best = d.get("best_valid")
        if d.get("classification") != "ACTUAL_RESULT":
            ERRORS.append(f"[FAIL] {n}: classification must be ACTUAL_RESULT")
        if d.get("status") != "valid_found":
            ERRORS.append(f"[FAIL] {n}: status must be valid_found")
        if not best:
            ERRORS.append(f"[FAIL] {n}: best_valid missing")
        elif _near(best.get("total_dv_proxy_kms"), 73.0, 0.2):
            ERRORS.append(f"[FAIL] {n}: old invalid total ~73 km/s leaked into no-lunar result")

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

    if n == "m6_complete_return_window_search.json":
        if d.get("event_semantics", {}).get("return_vinf_defined_only_at_earth_return") is not True:
            ERRORS.append(f"[FAIL] {n}: missing event semantics guard")
        for c in d.get("candidates", []):
            valid = c.get("valid_return_event")
            ret = c.get("return_vinf_kms")
            total = c.get("total_vinf_basis_kms")
            classification = c.get("classification")
            if valid is not True:
                if ret is not None:
                    ERRORS.append(f"[FAIL] {n}: {c.get('candidate_id')} invalid event has formal return_vinf_kms={ret}")
                if total is not None:
                    ERRORS.append(f"[FAIL] {n}: {c.get('candidate_id')} invalid event has formal total_vinf_basis_kms={total}")
            if ret is not None and (_near(ret, 77.88, 0.2) or ret >= 80.0):
                ERRORS.append(f"[FAIL] {n}: old invalid high return_vinf leaked into formal field: {ret}")
            if classification == "ACTUAL_RESULT" and valid is not True:
                ERRORS.append(f"[FAIL] {n}: ACTUAL_RESULT candidate must have valid_return_event=true")

    if n == "m6_numerical_deep_audit.json":
        if d.get("status") == "RED":
            ERRORS.append(f"[FAIL] {n}: status is RED")
        if d.get("classification") == "FINITE_SEARCH_NEG":
            if d.get("search_space") is None:
                ERRORS.append(f"[FAIL] {n}: FINITE_SEARCH_NEG missing search_space")
            if d.get("best_near_miss") is None:
                ERRORS.append(f"[FAIL] {n}: FINITE_SEARCH_NEG missing best_near_miss")
        for c in d.get("candidates", []):
            if c.get("classification") == "INVALID_LEGACY_EVENT" and c.get("return_vinf_kms") is not None:
                ERRORS.append(f"[FAIL] {n}: legacy invalid row leaked formal return_vinf_kms")
            formal = c.get("return_vinf_kms")
            if formal is not None and (_near(formal, 77.88, 0.2) or formal >= 80.0):
                ERRORS.append(f"[FAIL] {n}: forbidden formal return_vinf present: {formal}")

    if n == "m3_numerical_deep_audit.json":
        if d.get("no_daily_horizons_reset") is not True:
            ERRORS.append(f"[FAIL] {n}: no_daily_horizons_reset must be true")
        if d.get("classification") == "INDEPENDENT_JPL_VALIDATION":
            ERRORS.append(f"[FAIL] {n}: must not claim independent JPL validation")
        if d.get("classification") != "SAME_SOURCE_PROPAGATION_CHECK":
            ERRORS.append(f"[FAIL] {n}: classification must be SAME_SOURCE_PROPAGATION_CHECK")

resolved = RESULTS / "m5_saving_ratio_resolved.json"
compare = RESULTS / "m5_t61037_lunar_vs_no_lunar_deep_compare.json"
if compare.exists() and resolved.exists():
    resolved_json = json.loads(resolved.read_text(encoding="utf-8"))
    compare_json = json.loads(compare.read_text(encoding="utf-8"))
    if compare_json.get("formal_ratio_vinf_basis") is not None and resolved_json.get("formal_fixed_date_ratio") is None:
        ERRORS.append(
            "[FAIL] m5_saving_ratio_resolved.json: compare JSON is positive but resolved ratio is null"
        )

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
