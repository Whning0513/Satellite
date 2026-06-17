"""
refresh_legal_window_summary_fields.py
======================================
Lightweight summary refresh for existing legal-window result files.

This script does not rerun any search. It recomputes best-candidate summary
fields from stored candidate pools using the formal three-segment budget.
"""

from __future__ import annotations

import json
import csv
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(_REPO / "src"))

from budget_tools import best_lunar_candidate, ensure_lunar_row_formal_fields, lunar_candidate_sort_key
from experiments.legal_window_search_tools import summarize_legal_window_results


RESULTS = _REPO / "data" / "results"


def _load(name: str) -> tuple[Path, dict[str, Any]]:
    path = RESULTS / name
    return path, json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames = list(dict.fromkeys(key for row in rows for key in row.keys()))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _refresh_m5() -> None:
    path, data = _load("m5_legal_window_search.json")
    rows = sorted(
        [ensure_lunar_row_formal_fields(row) for row in data.get("search_rows", [])],
        key=lunar_candidate_sort_key,
    )
    data["search_rows"] = rows
    summary = summarize_legal_window_results(rows)
    data.update(summary)
    _write(path, data)
    _write_csv(RESULTS / "m5_legal_window_search.csv", rows)
    print(f"[refresh] {path.name}: best_lunar_candidate -> {summary['best_lunar_candidate']['t0_mjd']} / {summary['best_lunar_candidate']['r_m_km']}")


def _refresh_m6_file(name: str) -> None:
    path, data = _load(name)
    rows = sorted(
        [ensure_lunar_row_formal_fields(row) for row in data.get("candidates", [])],
        key=lunar_candidate_sort_key,
    )
    valid_rows = [row for row in rows if row.get("valid_return_event")]
    fair_rows = [row for row in rows if row.get("fair")]
    near_miss_rows = [row for row in rows if row.get("classification") != "ACTUAL_RESULT"]

    best_valid = best_lunar_candidate(fair_rows, fair_only=False)
    best_near_miss = min(near_miss_rows, key=lunar_candidate_sort_key) if near_miss_rows else None

    data["candidates"] = rows
    data["total_candidates_evaluated"] = len(rows)
    data["valid_complete_return_count"] = len(valid_rows)
    data["valid_fair_return_count"] = len(fair_rows)
    data["best_valid_candidate"] = best_valid
    data["best_near_miss"] = best_near_miss
    _write(path, data)
    _write_csv(RESULTS / path.with_suffix(".csv").name, rows)
    if best_valid is not None:
        print(
            f"[refresh] {path.name}: best_valid_candidate -> "
            f"{best_valid.get('t0_mjd')} / {best_valid.get('r_m_km')} / dv_total={best_valid.get('dv_total_kms')}"
        )
    else:
        print(f"[refresh] {path.name}: no fair valid candidate")


def main() -> int:
    _refresh_m5()
    for name in [
        "m6_independent_window_search.json",
        "m6_legal_window_search.json",
        "m6_complete_return_window_search.json",
    ]:
        path = RESULTS / name
        if path.exists():
            _refresh_m6_file(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
