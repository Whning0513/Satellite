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
    "o4plus_powered_mga_optimizer.json": "optional diagnostic file",
    "m5_global_no_lunar_baseline.json": "optional diagnostic file",
    "m6_pareto_window_diagnostic.json": "optional diagnostic file",
    "o3plus_vector_corrector.json": "optional diagnostic file",
    "o7_parallel_scan.json": "optional diagnostic file",
}
OPTIONAL_LABELS = {
    "o4plus": "o4plus_powered_mga_optimizer.json",
    "m5_global": "m5_global_no_lunar_baseline.json",
    "m6_pareto": "m6_pareto_window_diagnostic.json",
    "o3plus": "o3plus_vector_corrector.json",
    "o7_parallel": "o7_parallel_scan.json",
}


def _warn_missing(path_rel):
    canonical = OPTIONAL_LABELS.get(path_rel, path_rel)
    if canonical in OPTIONAL_MISSING_SEEN:
        return
    OPTIONAL_MISSING_SEEN.add(canonical)
    reason = OPTIONAL_FILES.get(canonical, "optional file")
    OPTIONAL_MISSING.append(f"[OPTIONAL] {canonical} — {reason} not generated")


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
    _check("figure_manifest.json",
           all(fig.get("exists") for fig in entries),
           "some referenced figures missing")


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
        "delta_v_budget_unified.json",
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
