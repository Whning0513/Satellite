"""
m5_legal_window_lunar_vs_no_lunar.py
====================================
Same-date no-lunar DSM baselines for top legal-window lunar candidates.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
RESULTS = _REPO / "data" / "results"
sys.path.insert(0, str(_REPO / "src"))

from budget_tools import (
    ensure_lunar_row_formal_fields,
    no_lunar_three_segment_budget,
    saving_ratio,
)


def _load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def _run_no_lunar(t0: float) -> dict:
    out = RESULTS / f"m5_no_lunar_fixed_date_deep_search_t{int(round(t0))}.json"
    cmd = [
        sys.executable,
        "src/experiments/m5_no_lunar_fixed_date_deep_search.py",
        "--t0",
        str(t0),
        "--output",
        str(out),
    ]
    subprocess.run(cmd, cwd=str(_REPO), check=True, text=True)
    return json.loads(out.read_text(encoding="utf-8"))


def _select_t0_values(search: dict) -> list[float]:
    rows = [ensure_lunar_row_formal_fields(row) for row in search.get("search_rows", [])]
    fair = [row for row in rows if row["fair"]]
    fair_sorted = sorted(fair, key=lambda row: (row["dv_total_kms"], row["distance_to_earth_km"]))
    selected = []
    for row in fair_sorted[:10]:
        selected.append(float(row["t0_mjd"]))
    for row in search.get("best_by_month", {}).values():
        selected.append(float(row["t0_mjd"]))
    return sorted(set(selected))


def main() -> int:
    search = _load("m5_legal_window_search.json")
    lunar_verify = _load("m5_best_lunar_candidate_verify.json")
    t0_values = _select_t0_values(search)
    rows = []

    search_rows = [ensure_lunar_row_formal_fields(row) for row in search["search_rows"]]
    by_t0_best = {}
    for row in search_rows:
        if not row["fair"]:
            continue
        prev = by_t0_best.get(row["t0_mjd"])
        if prev is None or (row["dv_total_kms"], row["distance_to_earth_km"]) < (
            prev["dv_total_kms"],
            prev["distance_to_earth_km"],
        ):
            by_t0_best[row["t0_mjd"]] = row

    for t0 in t0_values:
        lunar = by_t0_best[float(t0)]
        no_lunar = _run_no_lunar(float(t0))
        best_no_lunar = no_lunar.get("best_valid")
        formal_ratio = None
        no_lunar_total = None
        no_lunar_budget = None
        if best_no_lunar is not None:
            no_lunar_budget = no_lunar_three_segment_budget(
                departure_vinf_kms=float(best_no_lunar["departure_vinf_kms"]),
                dsm_delta_v_kms=float(best_no_lunar["dsm_delta_v_kms"]),
                return_vinf_kms=float(best_no_lunar["return_vinf_kms"]),
            )
            no_lunar_total = float(no_lunar_budget["dv_total_kms"])
            formal_ratio = round(saving_ratio(float(lunar["dv_total_kms"]), no_lunar_total), 6)
        rows.append(
            {
                "t0_mjd": float(t0),
                "t0_date": lunar["t0_date"],
                "lunar_valid": True,
                "budget_basis": "three_segment_formal",
                "lunar_dv_total_kms": float(lunar["dv_total_kms"]),
                "lunar_dv_launch_kms": float(lunar["dv_launch_kms"]),
                "lunar_dv_lunar_residual_kms": float(lunar["dv_lunar_residual_kms"]),
                "lunar_dv_reentry_kms": float(lunar["dv_reentry_kms"]),
                "lunar_total_vinf_basis_kms": lunar["total_vinf_basis_kms"],
                "lunar_return_vinf_kms": lunar["return_vinf_kms"],
                "no_lunar_valid": best_no_lunar is not None,
                "no_lunar_dv_total_kms": no_lunar_total,
                "no_lunar_dv_launch_kms": None if no_lunar_budget is None else no_lunar_budget["dv_launch_kms"],
                "no_lunar_dv_midcourse_kms": None if no_lunar_budget is None else no_lunar_budget["dv_midcourse_kms"],
                "no_lunar_dv_reentry_kms": None if no_lunar_budget is None else no_lunar_budget["dv_reentry_kms"],
                "no_lunar_total_vinf_basis_kms": None if best_no_lunar is None else float(best_no_lunar["total_dv_proxy_kms"]),
                "no_lunar_return_vinf_kms": best_no_lunar["return_vinf_kms"] if best_no_lunar else None,
                "same_t0": True,
                "same_budget_basis": True,
                "formal_ratio": formal_ratio,
                "classification": "ACTUAL_RESULT" if best_no_lunar is not None else "FINITE_SEARCH_NEG",
            }
        )

    best_ratio = max((row for row in rows if row["formal_ratio"] is not None), key=lambda row: row["formal_ratio"])
    payload = {
        "task": "M5 legal-window lunar vs no-lunar",
        "fixed_dates_compared": [row["t0_mjd"] for row in rows],
        "rows": rows,
        "best_legal_formal_ratio": best_ratio,
        "current_formal_ratio": next((row for row in rows if float(row["t0_mjd"]) == float(lunar_verify["candidate"]["t0_mjd"])), None),
        "classification": "LEGAL_WINDOW_SAME_DATE_COMPARE",
    }

    json_path = RESULTS / "m5_legal_window_lunar_vs_no_lunar.json"
    csv_path = RESULTS / "m5_legal_window_lunar_vs_no_lunar.csv"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved: {json_path}")
    print(f"Saved: {csv_path}")
    print(f"best legal formal ratio = {best_ratio['formal_ratio']} at t0={best_ratio['t0_mjd']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
