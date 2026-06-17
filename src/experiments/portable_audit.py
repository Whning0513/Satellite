"""
portable_audit.py
=================
Cross-platform engineering audit for the repository.

This replaces the old POSIX-only Makefile audit recipe.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mission_constraints import MISSION_LAUNCH_START_MJD, MISSION_LAUNCH_END_MJD

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "data" / "results"
MAKEFILE = REPO / "Makefile"
REPORT = REPO / "report.tex"
TOKEN_SENTINEL = "fce2a741a94feded5c3b9b7ab51f6748"
MAX_LARGE_FILE_BYTES = 5 * 1024 * 1024

FAILURES: list[str] = []
WARNINGS: list[str] = []

REQUIRED_SOURCE_FILES = [
    "src/validation.py",
    "src/event_semantics.py",
    "src/experiments/check_invalidated_formal_results.py",
    "src/experiments/check_m3_horizons_semantics.py",
    "src/experiments/check_m6_return_semantics.py",
    "src/experiments/check_m7_return_semantics.py",
    "src/experiments/check_result_schemas.py",
    "src/experiments/check_makefile_targets.py",
    "src/experiments/check_m5_fresh_reproducibility.py",
    "src/experiments/m3_numerical_deep_audit.py",
    "src/experiments/m5_saving_ratio_resolver.py",
    "src/experiments/m5_t61037_lunar_vs_no_lunar_deep_compare.py",
    "src/experiments/m6_complete_return_window_search.py",
    "src/experiments/m6_independent_spotcheck.py",
    "src/experiments/m6_numerical_deep_audit.py",
    "src/experiments/m7_extended_monte_carlo.py",
    "src/experiments/export_main_task_result.py",
]

REQUIRED_RESULT_FILES = [
    "data/results/m3_numerical_deep_audit.json",
    "data/results/m5_t61037_lunar_vs_no_lunar_deep_compare.json",
    "data/results/m5_saving_ratio_resolved.json",
    "data/results/m6_independent_spotcheck.json",
    "data/results/m6_numerical_deep_audit.json",
    "data/results/m7_extended_monte_carlo.json",
    "data/results/main_task_result.json",
    "data/results/main_task_trajectory.csv",
]

REQUIRED_TARGETS = [
    "m1",
    "m2",
    "m3-hierarchy",
    "m4",
    "repair-m5-real",
    "complete-lunar-return-search",
    "m5-lunar-best-fixed-date-compare",
    "m5-t61037-deep-compare",
    "m5-same-window-pareto",
    "m6-complete-window-search",
    "m6-independent-spotcheck",
    "m6-deep-audit",
    "check-m6-return-semantics",
    "m3-deep-audit",
    "check-m3-horizons-semantics",
    "check-invalidated-results",
    "return-semantics-test",
    "figure-manifest",
    "check-m7-return-semantics",
    "main-task-export",
    "audit",
]


def run_cmd(args: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(REPO),
        text=True,
        capture_output=True,
        check=check,
    )


def load_json(path: Path) -> dict | list:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def check_git_status() -> None:
    print("--- Git status ---")
    proc = run_cmd(["git", "status", "--short"])
    if proc.returncode != 0:
        FAILURES.append(f"git status failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return
    output = proc.stdout.strip()
    if output:
        WARNINGS.append("working tree is not clean")
        print(output)
    else:
        print("  [OK] git status clean")


def check_required_sources() -> None:
    print("\n--- Required source files ---")
    for rel in REQUIRED_SOURCE_FILES:
        path = REPO / rel
        if path.exists():
            print(f"  [OK] {rel}")
        else:
            FAILURES.append(f"missing required source file: {rel}")


def check_makefile_targets() -> None:
    print("\n--- Makefile targets ---")
    proc = run_cmd([sys.executable, "src/experiments/check_makefile_targets.py"])
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        FAILURES.append("check_makefile_targets.py reported failures")


def check_results_exist() -> None:
    print("\n--- Required result JSON ---")
    for rel in REQUIRED_RESULT_FILES:
        path = REPO / rel
        if path.exists():
            print(f"  [OK] {rel}")
        else:
            FAILURES.append(f"missing required result file: {rel}")


def check_m5_positive_ratio() -> None:
    print("\n--- M5 resolved ratio ---")
    resolved_path = RESULTS / "m5_saving_ratio_resolved.json"
    compare_path = RESULTS / "m5_fixed_date_current_compare.json"
    lunar_path = RESULTS / "m5_best_lunar_candidate_verify.json"
    if not resolved_path.exists() or not compare_path.exists():
        FAILURES.append("M5 resolved/compare JSON missing")
        return

    resolved = load_json(resolved_path)
    compare = load_json(compare_path)
    lunar = load_json(lunar_path) if lunar_path.exists() else {}

    status = resolved.get("status")
    ratio = resolved.get("formal_fixed_date_ratio")
    same_t0_mjd = resolved.get("same_t0_mjd")
    ratio_basis = resolved.get("ratio_basis")
    lunar_ok = resolved.get("lunar_valid_return_event")
    no_lunar_ok = resolved.get("no_lunar_valid_return_event")
    classification = resolved.get("classification")
    same_budget_basis = resolved.get("same_budget_basis")
    compare_ratio = compare.get("formal_ratio")
    compare_same_t0 = compare.get("same_t0")
    compare_same_budget = compare.get("same_budget_basis")
    compare_budget_basis = compare.get("budget_basis")
    lunar_t0 = lunar.get("candidate", {}).get("t0_mjd")
    lunar_launch_ok = lunar.get("candidate", {}).get("launch_window_valid")
    lunar_event_ok = lunar.get("event_check", {}).get("valid_return_event")

    print(f"  status = {status}")
    print(f"  formal_fixed_date_ratio = {ratio}")
    print(f"  compare formal_ratio = {compare_ratio}")
    print(f"  same_t0_mjd = {same_t0_mjd}")
    print(f"  same_budget_basis = {same_budget_basis}")
    print(f"  ratio_basis = {ratio_basis}")
    print(f"  lunar_valid_return_event = {lunar_ok}")
    print(f"  no_lunar_valid_return_event = {no_lunar_ok}")
    print(f"  classification = {classification}")

    compare_in_window = (
        compare_same_t0 is not None
        and MISSION_LAUNCH_START_MJD <= float(compare_same_t0) <= MISSION_LAUNCH_END_MJD
    )
    resolved_in_window = (
        same_t0_mjd is not None
        and MISSION_LAUNCH_START_MJD <= float(same_t0_mjd) <= MISSION_LAUNCH_END_MJD
    )

    if not compare_in_window:
        FAILURES.append("current M5 compare JSON is outside the formal 2026 launch window")
        return

    if status == "historical_anchor_invalidated":
        if ratio is not None:
            FAILURES.append("historical invalidated resolver must not expose a formal_fixed_date_ratio")
    elif status == "formal_fixed_date_positive_ratio":
        if not resolved_in_window:
            FAILURES.append("formal_fixed_date_positive_ratio resolver is outside the formal 2026 launch window")
        if ratio is None or ratio <= 0:
            FAILURES.append(f"unexpected M5 formal ratio: {ratio}")
    else:
        FAILURES.append(f"unexpected M5 resolved status: {status}")

    if ratio is not None and ratio <= 0:
        FAILURES.append(f"unexpected non-positive M5 formal ratio: {ratio}")
    if compare_ratio is None or compare_ratio <= 0:
        FAILURES.append(f"unexpected compare ratio: {compare_ratio}")
    if compare_same_budget is not True:
        FAILURES.append("same_budget_basis must be true in current compare JSON")
    if status == "formal_fixed_date_positive_ratio" and same_budget_basis is not True:
        FAILURES.append("same_budget_basis must be true in resolved JSON when it exposes a formal ratio")
    if compare_budget_basis != "three_segment_formal":
        FAILURES.append(f"unexpected compare budget basis: {compare_budget_basis}")
    if status == "formal_fixed_date_positive_ratio" and ratio_basis != "three_segment_formal":
        FAILURES.append(f"unexpected ratio basis: {ratio_basis}")
    if compare.get("lunar_valid") is not True or compare.get("no_lunar_valid") is not True:
        FAILURES.append("current M5 compare JSON does not confirm both valid return events")
    if lunar_launch_ok is not True or lunar_event_ok is not True:
        FAILURES.append("current M5 lunar best candidate is not a valid in-window Earth-return event")
    if lunar_t0 != compare_same_t0:
        FAILURES.append(f"M5 compare/lunar t0 mismatch: compare={compare_same_t0}, lunar={lunar_t0}")
    if classification not in ("ACTUAL_RESULT", "UNRESOLVED"):
        FAILURES.append(f"unexpected M5 resolved classification: {classification}")


def check_invalidated_values() -> None:
    print("\n--- Invalidated value guard ---")
    proc = run_cmd([sys.executable, "src/experiments/check_invalidated_formal_results.py"])
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        FAILURES.append("check_invalidated_formal_results.py reported failures")


def check_m7_return_semantics() -> None:
    print("\n--- M7 return semantics ---")
    proc = run_cmd([sys.executable, "src/experiments/check_m7_return_semantics.py"])
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        FAILURES.append("check_m7_return_semantics.py reported failures")


def check_m6_return_semantics() -> None:
    print("\n--- M6 return semantics ---")
    proc = run_cmd([sys.executable, "src/experiments/check_m6_return_semantics.py"])
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        FAILURES.append("check_m6_return_semantics.py reported failures")


def check_m3_horizons_semantics() -> None:
    print("\n--- M3 Horizons semantics ---")
    proc = run_cmd([sys.executable, "src/experiments/check_m3_horizons_semantics.py"])
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        FAILURES.append("check_m3_horizons_semantics.py reported failures")


def check_figure_manifest() -> None:
    print("\n--- Figure manifest ---")
    path = RESULTS / "figure_manifest.json"
    if not path.exists():
        FAILURES.append("figure_manifest.json missing")
        return

    manifest = load_json(path)
    entries: list[dict]
    if isinstance(manifest, dict):
        entries = manifest.get("figure_manifest", [])
    elif isinstance(manifest, list):
        entries = manifest
    else:
        FAILURES.append("figure_manifest.json has unexpected type")
        return

    if not entries:
        FAILURES.append("figure_manifest.json has no entries")
        return

    missing = [entry.get("file") or entry.get("filename") for entry in entries if not entry.get("exists")]
    print(f"  entries = {len(entries)}")
    if missing:
        WARNINGS.append(f"figure manifest has missing entries: {missing}")
        print(f"  [WARN] missing figures: {missing}")
    else:
        print("  [OK] all manifest entries exist")


def check_security() -> None:
    print("\n--- Security ---")
    tracked_config = run_cmd(["git", "ls-files", "config/"])
    if tracked_config.returncode != 0:
        FAILURES.append(f"git ls-files config/ failed: {tracked_config.stderr.strip()}")
    elif tracked_config.stdout.strip():
        WARNINGS.append("config/ is tracked")
        print("  [WARN] config/ is tracked")
    else:
        print("  [OK] config/ is gitignored")

    grep = run_cmd(["git", "grep", "-l", TOKEN_SENTINEL])
    if grep.returncode not in (0, 1):
        FAILURES.append(f"git grep token scan failed: {grep.stderr.strip()}")
    else:
        hits = [
            line.strip()
            for line in grep.stdout.splitlines()
            if line.strip()
            and Path(line.strip()).name != "Makefile"
            and Path(line.strip()).name != "portable_audit.py"
        ]
        if hits:
            FAILURES.append(f"token sentinel found in tracked files: {hits}")
        else:
            print("  [OK] no token leaks")


def check_large_files() -> None:
    print("\n--- Large files (>5 MB) ---")
    large: list[str] = []
    for path in REPO.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        try:
            if path.stat().st_size > MAX_LARGE_FILE_BYTES:
                large.append(str(path.relative_to(REPO)))
        except OSError as exc:
            WARNINGS.append(f"could not stat file {path}: {exc}")
    if large:
        WARNINGS.append(f"large files present: {large[:5]}")
        print("  [WARN] large files detected")
        for rel in large[:5]:
            print(f"    {rel}")
    else:
        print("  [OK] no files >5 MB")


def check_repo_size() -> None:
    print("\n--- Repo size ---")
    total = 0
    for path in REPO.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        try:
            total += path.stat().st_size
        except OSError:
            continue
    mib = total / (1024 * 1024)
    print(f"  {mib:.1f} MiB")


def check_report_figure_references() -> None:
    print("\n--- Figure reference check (report.tex -> data/results/) ---")
    if not REPORT.exists():
        FAILURES.append("report.tex missing")
        return
    tex = REPORT.read_text(encoding="utf-8")
    refs = set(re.findall(r"data/results/[^}\s]+\.png", tex))
    refs.update(re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+\.png)\}", tex))
    refs = sorted(refs)
    if not refs:
        WARNINGS.append("no report figure references found")
        print("  [WARN] no referenced figures found in report.tex")
        return
    missing = []
    for ref in refs:
        if "/" in ref:
            path = REPO / ref
            shown = ref
        else:
            path = RESULTS / ref
            shown = f"data/results/{ref}"
        if path.exists():
            print(f"  [OK] {shown}")
        else:
            print(f"  [MISS] {shown}")
            missing.append(shown)
    if missing:
        WARNINGS.append(f"missing report figures: {missing}")
    else:
        print("  All figures present.")


def check_m5_result_files() -> None:
    print("\n--- M5 result files ---")
    files = [
        "data/results/m5_fair_no_lunar_baseline.json",
        "data/results/m5_fair_no_lunar_baseline.csv",
        "data/results/m5_no_lunar_lambert_baseline.json",
        "data/results/m5_no_lunar_lambert_baseline.csv",
        "data/results/m5_no_lunar_lambert_pareto_t061066.json",
        "data/results/m5_no_lunar_lambert_pareto.png",
        "data/results/m5_no_lunar_lambert_pareto_t061154.json",
    ]
    for rel in files:
        path = REPO / rel
        if path.exists():
            print(f"  [OK] {rel}")
        else:
            WARNINGS.append(f"optional M5 audit artifact missing: {rel}")
            print(f"  [MISS] {rel}")


def check_windows_path_compatibility() -> None:
    print("\n--- Windows path compatibility ---")
    text = MAKEFILE.read_text(encoding="utf-8")
    shell_lines = []
    in_legacy_block = False
    for line_no, line in enumerate(text.splitlines(), start=1):
        if re.match(r"^audit-posix-legacy:", line):
            in_legacy_block = True
            continue
        if in_legacy_block and line and not line.startswith("\t"):
            in_legacy_block = False
        if in_legacy_block or line.lstrip().startswith("#") or not line.startswith("\t"):
            continue
        if re.search(r"\bgrep\b|\bfind\b|\brm\b|\bdu\b|\bawk\b|\bhead\b|\bfor\b|\[\s*-n|;\s*then\b|\bfi\b", line):
            shell_lines.append((line_no, line))

    if shell_lines:
        print("  [WARN] remaining shell-specific lines in Makefile:")
        for line_no, line in shell_lines[:10]:
            print(f"    {line_no}: {line}")
        WARNINGS.append(f"Makefile still has {len(shell_lines)} shell-specific lines")
    else:
        print("  [OK] no obvious shell-specific audit/clean lines remain")


def check_m5_fresh_repro_guard() -> None:
    print("\n--- M5 fresh reproducibility guard ---")
    proc = run_cmd([sys.executable, "src/experiments/check_m5_fresh_reproducibility.py"])
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        FAILURES.append("check_m5_fresh_reproducibility.py reported failures")


def main() -> int:
    print("=== Portable audit ===")
    print(f"repo = {REPO}")
    print(f"platform = {os.name}")

    check_security()
    check_large_files()
    check_repo_size()
    check_git_status()
    check_required_sources()
    check_makefile_targets()
    check_results_exist()
    check_m5_positive_ratio()
    check_m3_horizons_semantics()
    check_m6_return_semantics()
    check_m7_return_semantics()
    check_invalidated_values()
    check_m5_fresh_repro_guard()
    check_figure_manifest()
    check_report_figure_references()
    check_m5_result_files()
    check_windows_path_compatibility()

    print("\n--- Summary ---")
    print(f"  failures = {len(FAILURES)}")
    print(f"  warnings = {len(WARNINGS)}")
    for item in WARNINGS:
        print(f"  [WARN] {item}")
    if FAILURES:
        for item in FAILURES:
            print(f"  [FAIL] {item}")
        return 1
    print("  [OK] audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
