"""
check_m5_fresh_reproducibility.py
=================================
Lightweight guard for the M5 fresh-result pipeline.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MAKEFILE = REPO / "Makefile"
RESULTS = REPO / "data" / "results"

EXPECTED_PIPELINE = [
    "experiments/m5_lunar_return_local_refine.py",
    "experiments/m5_best_lunar_candidate_verify.py",
    "experiments/m5_no_lunar_fixed_date_deep_search.py",
    "experiments/m5_fixed_date_current_compare.py",
    "experiments/m5_same_window_lunar_no_lunar_pareto.py",
    "experiments/m5_saving_ratio_resolver.py",
]


def extract_recipe_block(text: str, target: str) -> list[str]:
    lines = text.splitlines()
    capture = False
    recipe: list[str] = []
    for line in lines:
        if re.match(rf"^{re.escape(target)}:", line):
            capture = True
            continue
        if capture and line and not line.startswith("\t"):
            break
        if capture and line.startswith("\t"):
            recipe.append(line.strip())
    return recipe


def load_json(name: str) -> dict:
    path = RESULTS / name
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    failures: list[str] = []
    print("=== M5 fresh reproducibility guard ===")

    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    recipe = extract_recipe_block(makefile_text, "repair-m5-real")
    if not recipe:
        failures.append("repair-m5-real target not found")
    else:
        print("repair-m5-real recipe:")
        for line in recipe:
            print(f"  {line}")
        for expected in EXPECTED_PIPELINE:
            if not any(expected in line for line in recipe):
                failures.append(f"repair-m5-real missing pipeline step: {expected}")

    fast_recipe = extract_recipe_block(makefile_text, "repair-m5-real-fast")
    if not fast_recipe:
        failures.append("repair-m5-real-fast target not found")

    compare = load_json("m5_fixed_date_current_compare.json")
    lunar = load_json("m5_best_lunar_candidate_verify.json")
    resolved = load_json("m5_saving_ratio_resolved.json")

    ratio = compare.get("formal_ratio")
    if ratio is None or ratio <= 0:
        failures.append(f"current compare formal ratio mismatch: {ratio}")
    current_t0 = compare.get("same_t0")
    lunar_t0 = lunar.get("candidate", {}).get("t0_mjd")
    if current_t0 != lunar_t0:
        failures.append(f"compare same_t0 mismatch: compare={current_t0}, lunar={lunar_t0}")
    if compare.get("same_budget_basis") is not True:
        failures.append(
            f"compare same_budget_basis mismatch: {compare.get('same_budget_basis')}"
        )
    if compare.get("budget_basis") != "three_segment_formal":
        failures.append(f"compare budget_basis mismatch: {compare.get('budget_basis')}")
    lunar_total = compare.get("lunar_total_dv_kms")
    no_lunar_total = compare.get("no_lunar_total_dv_kms")
    if lunar_total is None or no_lunar_total is None:
        failures.append("compare JSON missing formal three-segment totals")
    if compare.get("lunar_valid") is not True or compare.get("no_lunar_valid") is not True:
        failures.append("compare JSON does not confirm both valid trajectories")
    if compare.get("launch_window_valid") is not True:
        failures.append("compare JSON launch_window_valid is not true")
    if lunar.get("candidate", {}).get("launch_window_valid") is not True:
        failures.append("lunar candidate launch_window_valid is not true")
    if lunar.get("event_check", {}).get("valid_return_event") is not True:
        failures.append("lunar best candidate does not confirm a valid Earth-return event")

    resolved_status = resolved.get("status")
    if resolved_status not in ("historical_anchor_invalidated", "formal_fixed_date_positive_ratio"):
        failures.append(f"resolved status mismatch: {resolved_status}")

    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}")
        return 1

    print("[OK] M5 pipeline and resolved result guards passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
