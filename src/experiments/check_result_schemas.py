"""
check_result_schemas.py
=======================
Lightweight schema check for existing result JSON files.
Does NOT regenerate any result — only checks what exists.
"""

import json, math, sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
RESULTS = _REPO / "data" / "results"

ERRORS = []
WARNINGS = []
OPTIONAL_MISSING = []
OPTIONAL_MISSING_SEEN = set()

OPTIONAL_FILES = {
    "delta_v_budget_unified.json": "optional diagnostic file",
    "o4plus_powered_mga_optimizer.json": "optional diagnostic file",
    "m5_global_no_lunar_baseline.json": "optional diagnostic file",
    "m6_pareto_window_diagnostic.json": "optional diagnostic file",
    "o3plus_vector_corrector.json": "optional diagnostic file",
    "o7_parallel_scan.json": "optional diagnostic file",
    "m7_extended_monte_carlo_profile.json": "optional M7 profiling file",
    "m7_extended_monte_carlo_smoke.json": "optional M7 smoke semantics file",
}
OPTIONAL_LABELS = {
    "o4plus": "o4plus_powered_mga_optimizer.json",
    "m5_global": "m5_global_no_lunar_baseline.json",
    "m6_pareto": "m6_pareto_window_diagnostic.json",
    "o3plus": "o3plus_vector_corrector.json",
    "o7_parallel": "o7_parallel_scan.json",
    "m7_mc_profile": "m7_extended_monte_carlo_profile.json",
    "m7_mc_smoke": "m7_extended_monte_carlo_smoke.json",
}


def _warn_missing(path_rel):
    canonical = OPTIONAL_LABELS.get(path_rel, path_rel)
    if canonical in OPTIONAL_MISSING_SEEN:
        return
    OPTIONAL_MISSING_SEEN.add(canonical)
    reason = OPTIONAL_FILES.get(canonical, "optional file")
    OPTIONAL_MISSING.append(f"[OPTIONAL] {canonical} - {reason} not generated")


def _check(path_rel, condition, msg):
    path = RESULTS / path_rel
    if not path.exists():
        if path_rel in OPTIONAL_FILES or path_rel in OPTIONAL_LABELS:
            _warn_missing(path_rel)
        else:
            ERRORS.append(f"[FAIL] {path_rel}: required file not found")
        return
    if not condition:
        ERRORS.append(f"[FAIL] {path_rel}: {msg}")
    else:
        print(f"  [OK] {path_rel}")


def _load(path_rel):
    path = RESULTS / path_rel
    if not path.exists():
        if path_rel in OPTIONAL_FILES or path_rel in OPTIONAL_LABELS:
            _warn_missing(path_rel)
        else:
            ERRORS.append(f"[FAIL] {path_rel}: required file not found")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _finite(obj, path=""):
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return False
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if not _finite(v, f"{path}.{k}"):
                return False
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if not _finite(v, f"{path}[{i}]"):
                return False
    return True


def check_delta_v_budget():
    d = _load("delta_v_budget_unified.json")
    if d is None:
        return
    _check("delta_v_budget_unified.json",
           "qian_symmetric" in d and "m1_symmetric" in d,
           "missing expected keys")
    _check("delta_v_budget_unified.json",
           _finite(d),
           "NaN/Inf detected")


def check_figure_manifest():
    d = _load("figure_manifest.json")
    if d is None:
        return
    entries = d["figure_manifest"] if isinstance(d, dict) and "figure_manifest" in d else d
    _check("figure_manifest.json",
           isinstance(entries, list) and len(entries) >= 8,
           "should have at least 8 entries")
    _check("figure_manifest.json",
           all(isinstance(fig, dict) for fig in entries),
           "entries must be objects")
    missing = [fig for fig in entries if not fig.get("exists")]
    if missing:
        WARNINGS.append(
            "[OPTIONAL] figure_manifest.json - some referenced figures are not generated in current working state"
        )
        print(f"  [WARN] figure_manifest.json has {len(missing)} missing referenced figures")
    else:
        print("  [OK] figure_manifest.json all referenced figures exist")


def check_m7_outputs():
    full = _load("m7_extended_monte_carlo.json")
    if full is None:
        ERRORS.append("[FAIL] m7_extended_monte_carlo.json: required file not found for full-stage validation")
        return

    _check("m7_extended_monte_carlo.json", full.get("n") == 200, "expected n = 200")
    _check(
        "m7_extended_monte_carlo.json",
        full.get("classification") == "FULL_MC_ACTUAL_RESULT",
        f"expected classification FULL_MC_ACTUAL_RESULT, got {full.get('classification')!r}",
    )
    for key in [
        "seed",
        "valid_return_count",
        "valid_return_rate",
        "return_vinf_valid_only",
        "total_vinf_basis_valid_only",
        "old_invalid_return_vinf_guard",
    ]:
        _check("m7_extended_monte_carlo.json", key in full, f"missing required key {key}")
    if full.get("return_vinf_valid_only") is not None:
        stats = full["return_vinf_valid_only"]
        _check("m7_extended_monte_carlo.json", stats.get("p95", 0) < 30.0, "formal return_vinf p95 unexpectedly large")
        _check("m7_extended_monte_carlo.json", abs(stats.get("mean", 0.0) - 79.0) > 5.0, "formal return_vinf mean still near old invalid ~79 km/s")
    _check(
        "m7_extended_monte_carlo.json",
        full.get("old_invalid_return_vinf_guard") is True,
        "old_invalid_return_vinf_guard must be true",
    )
    _check(
        "m7_extended_monte_carlo.json",
        full.get("event_semantics", {}).get("return_vinf_defined_only_at_earth_return") is True,
        "missing return-event semantics guard",
    )

    smoke = _load("m7_extended_monte_carlo_smoke.json")
    if smoke is not None:
        _check(
            "m7_extended_monte_carlo_smoke.json",
            smoke.get("classification") == "SMOKE_SEMANTICS_RESULT",
            f"expected SMOKE_SEMANTICS_RESULT, got {smoke.get('classification')!r}",
        )
    else:
        _warn_missing("m7_mc_smoke")

    profile = _load("m7_extended_monte_carlo_profile.json")
    if profile is None:
        _warn_missing("m7_mc_profile")


def check_m3_outputs():
    full = _load("m3_numerical_deep_audit.json")
    if full is None:
        ERRORS.append("[FAIL] m3_numerical_deep_audit.json: required file not found for M3 deep validation")
        return

    _check(
        "m3_numerical_deep_audit.json",
        full.get("uses_day0_initial_condition_only") is True,
        "uses_day0_initial_condition_only must be true",
    )
    _check(
        "m3_numerical_deep_audit.json",
        full.get("no_daily_horizons_reset") is True,
        "no_daily_horizons_reset must be true",
    )
    _check(
        "m3_numerical_deep_audit.json",
        full.get("classification") == "SAME_SOURCE_PROPAGATION_CHECK",
        f"expected SAME_SOURCE_PROPAGATION_CHECK, got {full.get('classification')!r}",
    )
    _check(
        "m3_numerical_deep_audit.json",
        full.get("not_independent_jpl_prediction") is True,
        "not_independent_jpl_prediction must be true",
    )
    for key in [
        "models",
        "dt_convergence",
        "frame_definitions",
    ]:
        _check("m3_numerical_deep_audit.json", key in full, f"missing required key {key}")
    models = full.get("models", {})
    for model_key in ["3body_sun_earth_moon", "5body_sem_jupiter_venus", "full_planetary"]:
        block = models.get(model_key)
        _check("m3_numerical_deep_audit.json", isinstance(block, dict), f"missing model block {model_key}")
        if isinstance(block, dict):
            for key in ["frame", "residual_km", "heliocentric_residual_km"]:
                _check("m3_numerical_deep_audit.json", key in block, f"{model_key} missing required key {key}")
    _check(
        "m3_numerical_deep_audit.json",
        "ssb_residual_km" in models.get("3body_sun_earth_moon", {}),
        "3body_sun_earth_moon missing ssb_residual_km",
    )
    _check(
        "m3_numerical_deep_audit.json",
        "heliocentric_residual_km" not in full and "ssb_absolute_residual_km" not in full,
        "top-level unlabeled residual fields should not exist",
    )
    dt_obj = full.get("dt_convergence", {})
    _check(
        "m3_numerical_deep_audit.json",
        isinstance(dt_obj, dict) and dt_obj.get("model") == "3body_or_missing_perturbation_test",
        "dt_convergence.model must identify the 3-body test",
    )
    dt_rows = dt_obj.get("values", []) if isinstance(dt_obj, dict) else []
    _check(
        "m3_numerical_deep_audit.json",
        isinstance(dt_rows, list) and len(dt_rows) >= 3,
        "dt_convergence must contain at least 3 rows",
    )


def check_m6_outputs():
    full = _load("m6_numerical_deep_audit.json")
    if full is None:
        ERRORS.append("[FAIL] m6_numerical_deep_audit.json: required file not found for M6 deep validation")
        return

    _check(
        "m6_numerical_deep_audit.json",
        full.get("classification") in ("ACTUAL_RESULT", "ACTUAL_RESULT_M5_DERIVED_WINDOW", "FINITE_SEARCH_NEG"),
        f"unexpected classification {full.get('classification')!r}",
    )
    _check(
        "m6_numerical_deep_audit.json",
        full.get("status") in ("PASS", "WARN"),
        f"status should be PASS/WARN, got {full.get('status')!r}",
    )
    for key in [
        "candidate_source",
        "source_file",
        "source_grid_reused",
        "independent_m6_search",
        "m6_interpretation",
        "search_window_mjd",
        "t0_values",
        "rm_values_km",
        "side_values",
        "search_space",
        "candidate_count",
        "legacy_candidate_count",
        "complete_search_candidate_count",
        "best_near_miss",
        "event_semantics",
        "candidates",
        "independent_spotcheck",
    ]:
        _check("m6_numerical_deep_audit.json", key in full, f"missing required key {key}")

    semantics = full.get("event_semantics", {})
    _check(
        "m6_numerical_deep_audit.json",
        semantics.get("return_vinf_defined_only_at_earth_return") is True,
        "missing return-event semantics guard",
    )
    if full.get("classification") == "FINITE_SEARCH_NEG":
        _check("m6_numerical_deep_audit.json", full.get("search_space") is not None, "FINITE_SEARCH_NEG missing search_space")
        _check("m6_numerical_deep_audit.json", full.get("best_near_miss") is not None, "FINITE_SEARCH_NEG missing best_near_miss")
    if full.get("classification") == "ACTUAL_RESULT_M5_DERIVED_WINDOW":
        _check(
            "m6_numerical_deep_audit.json",
            full.get("candidate_source") == "m5_lunar_return_local_refine_grid",
            f"expected candidate_source m5_lunar_return_local_refine_grid, got {full.get('candidate_source')!r}",
        )
        _check(
            "m6_numerical_deep_audit.json",
            full.get("source_grid_reused") is True and full.get("independent_m6_search") is False,
            "M5-derived deep audit must declare reused source grid and non-independent search",
        )

    search = _load("m6_complete_return_window_search.json")
    if search is None:
        ERRORS.append("[FAIL] m6_complete_return_window_search.json: required file not found")
        return
    for key in [
        "candidate_source",
        "source_file",
        "source_grid_reused",
        "independent_m6_search",
        "m6_interpretation",
        "search_window_mjd",
        "t0_values",
        "rm_values_km",
        "side_values",
        "not_a_legacy_perihelion_vinf_search",
    ]:
        _check("m6_complete_return_window_search.json", key in search, f"missing required provenance key {key}")
    _check(
        "m6_complete_return_window_search.json",
        search.get("event_semantics", {}).get("return_vinf_defined_only_at_earth_return") is True,
        "missing return-event semantics guard",
    )
    if search.get("source_grid_reused") is True:
        _check(
            "m6_complete_return_window_search.json",
            search.get("classification") == "ACTUAL_RESULT_M5_DERIVED_WINDOW",
            f"expected ACTUAL_RESULT_M5_DERIVED_WINDOW, got {search.get('classification')!r}",
        )
    spot = _load("m6_independent_spotcheck.json")
    if spot is None:
        ERRORS.append("[FAIL] m6_independent_spotcheck.json: required file not found")
    else:
        _check("m6_independent_spotcheck.json", spot.get("candidates_recomputed", 0) >= 2, "too few spotchecked candidates")
        _check("m6_independent_spotcheck.json", spot.get("status") in ("PASS", "WARN"), f"unexpected status {spot.get('status')!r}")
    _check(
        "m6_complete_return_window_search.json",
        search.get("status") in ("valid_complete_return_found", "finite_search_negative"),
        f"unexpected status {search.get('status')!r}",
    )


def check_o4plus():
    d = _load("o4plus_powered_mga_optimizer.json")
    if d is None:
        return
    _check("o4plus", "best_candidate" in d, "missing best_candidate")
    _check("o4plus", d.get("uses_scipy_optimize") is False, "uses scipy?")
    if "best_candidate" in d:
        _check("o4plus", _finite(d["best_candidate"]), "NaN/Inf in best")


def check_m5_global():
    d = _load("m5_global_no_lunar_baseline.json")
    if d is None:
        return
    _check("m5_global", "num_fair_baseline" in d, "missing num_fair_baseline")
    _check("m5_global", _finite(d), "NaN/Inf detected")


def check_m6_pareto():
    d = _load("m6_pareto_window_diagnostic.json")
    if d is None:
        return
    _check("m6_pareto", "best_by_perihelion" in d, "missing best_by")
    _check("m6_pareto", _finite(d), "NaN/Inf detected")


def check_o3plus():
    d = _load("o3plus_vector_corrector.json")
    if d is None:
        return
    _check("o3plus", "uses_scipy_optimize" in d, "missing uses_scipy")
    if "uses_scipy_optimize" in d:
        _check("o3plus", d["uses_scipy_optimize"] is False, "uses scipy?")
    _check("o3plus", "best_result" in d, "missing best_result")
    if "best_result" in d:
        _check("o3plus",
               d["best_result"].get("converged") is True,
               "best candidate not converged")
        _check("o3plus", _finite(d["best_result"]), "NaN/Inf")


def check_o7_parallel():
    d = _load("o7_parallel_scan.json")
    if d is None:
        return
    _check("o7_parallel",
           d.get("results_identical") is True,
           "results not identical")
    _check("o7_parallel", _finite(d), "NaN/Inf")


def main():
    print("=" * 66)
    print("Result schema check (existing files only)")
    print("=" * 66)

    for fn in [
        "figure_manifest.json",
    ]:
        path = RESULTS / fn
        _check(fn, path.exists() if path.exists() else True,
               f"{fn} not found (OK if generated by make)")

    check_delta_v_budget()
    check_figure_manifest()
    check_o4plus()
    check_m5_global()
    check_m6_pareto()
    check_o3plus()
    check_o7_parallel()
    check_m3_outputs()
    check_m6_outputs()
    check_m7_outputs()

    print(f"\n  Errors:   {len(ERRORS)}")
    print(f"  Warnings: {len(WARNINGS) + len(OPTIONAL_MISSING)}")

    for w in WARNINGS:
        print(f"    {w}")
    for w in OPTIONAL_MISSING:
        print(f"    {w}")

    if ERRORS:
        print("\n  ERRORS (need fixing):")
        for e in ERRORS:
            print(f"    {e}")
        sys.exit(1)
    else:
        print("\n  All checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
