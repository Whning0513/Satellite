"""
m6_numerical_deep_audit.py
==========================
Numerical deep audit for M6 launch-window results.

This script merges:
  1. legacy top-candidate event audit (known invalid formal return_vinf semantics)
  2. new complete-return window search results

Output:
  data/results/m6_numerical_deep_audit.json
  data/results/m6_numerical_deep_audit.csv
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

RESULTS = _REPO / "data" / "results"


def _load(name: str) -> dict | None:
    path = RESULTS / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _legacy_rows(event_json: dict) -> list[dict]:
    rows = []
    for idx, row in enumerate(event_json.get("results", []), start=1):
        rows.append(
            {
                "candidate_id": f"legacy_top_{idx}",
                "t0_mjd": row.get("t0_mjd"),
                "source_file": "data/results/m6_lunar_return_event_audit.json",
                "legacy_return_vinf_kms": row.get("end_of_S5_claimed_return_vinf_kms"),
                "valid_return_event": bool(row.get("valid_earth_return_event")),
                "distance_to_earth_km": row.get("end_of_S5_dist_to_earth_km"),
                "return_event_mjd": None,
                "return_vinf_kms": row.get("formal_return_vinf_kms"),
                "perihelion_AU": row.get("end_of_S5_sc_sun_r_AU"),
                "total_vinf_basis_kms": None,
                "classification": "INVALID_LEGACY_EVENT",
                "reason": row.get("return_event_reason"),
            }
        )
    return rows


def _search_rows(search_json: dict) -> list[dict]:
    rows = []
    for row in search_json.get("candidates", []):
        rows.append(
            {
                "candidate_id": row.get("candidate_id"),
                "t0_mjd": row.get("t0_mjd"),
                "source_file": row.get("source_file"),
                "legacy_return_vinf_kms": row.get("legacy_return_vinf_kms"),
                "valid_return_event": bool(row.get("valid_return_event")),
                "distance_to_earth_km": row.get("distance_to_earth_km"),
                "return_event_mjd": row.get("return_event_mjd"),
                "return_vinf_kms": row.get("return_vinf_kms"),
                "perihelion_AU": row.get("perihelion_AU"),
                "total_vinf_basis_kms": row.get("total_vinf_basis_kms"),
                "classification": row.get("classification"),
                "reason": row.get("reason"),
            }
        )
    return rows


def main() -> None:
    legacy = _load("m6_lunar_return_event_audit.json")
    search = _load("m6_complete_return_window_search.json")
    spotcheck = _load("m6_independent_spotcheck.json")

    red_flags: list[str] = []
    if legacy is None:
        red_flags.append("missing data/results/m6_lunar_return_event_audit.json")
    if search is None:
        red_flags.append("missing data/results/m6_complete_return_window_search.json")
    if spotcheck is None:
        red_flags.append("missing data/results/m6_independent_spotcheck.json")

    rows: list[dict] = []
    if legacy is not None:
        rows.extend(_legacy_rows(legacy))
    if search is not None:
        rows.extend(_search_rows(search))

    legacy_rows = [row for row in rows if row["classification"] == "INVALID_LEGACY_EVENT"]
    actual_rows = [row for row in rows if row["classification"] == "ACTUAL_RESULT"]
    near_miss_rows = [row for row in rows if row["classification"] == "NEAR_MISS"]

    old_invalid_formal_count = 0
    for row in legacy_rows:
        claimed = row.get("legacy_return_vinf_kms")
        formal = row.get("return_vinf_kms")
        if claimed is not None and float(claimed) >= 30.0:
            if formal is not None:
                old_invalid_formal_count += 1
                red_flags.append(
                    f"legacy candidate t0={row.get('t0_mjd')} leaked formal return_vinf={formal}"
                )

    for row in actual_rows:
        if not row["valid_return_event"]:
            red_flags.append(f"ACTUAL_RESULT candidate {row['candidate_id']} missing valid_return_event")
        if row.get("return_vinf_kms") is None:
            red_flags.append(f"ACTUAL_RESULT candidate {row['candidate_id']} missing return_vinf_kms")

    classification = search.get("classification") if search else ("FINITE_SEARCH_NEG" if not actual_rows else "ACTUAL_RESULT")
    if classification == "FINITE_SEARCH_NEG" and search is not None:
        if search.get("search_space") is None:
            red_flags.append("FINITE_SEARCH_NEG missing search_space")
        if search.get("best_near_miss") is None:
            red_flags.append("FINITE_SEARCH_NEG missing best_near_miss")

    best_valid = search.get("best_valid_candidate") if search else None
    best_near_miss = search.get("best_near_miss") if search else None
    status = "RED" if red_flags else "PASS"

    payload = {
        "task": "M6 numerical deep audit",
        "classification": classification,
        "status": status,
        "source_file": "data/results/m6_complete_return_window_search.json",
        "candidate_source": search.get("candidate_source") if search else None,
        "source_grid_reused": search.get("source_grid_reused") if search else None,
        "independent_m6_search": search.get("independent_m6_search") if search else None,
        "m6_interpretation": search.get("m6_interpretation") if search else None,
        "legacy_source_file": "data/results/m6_lunar_return_event_audit.json",
        "complete_return_search_source_file": "data/results/m6_complete_return_window_search.json",
        "spotcheck_source_file": "data/results/m6_independent_spotcheck.json",
        "search_space": search.get("search_space") if search else None,
        "search_window_mjd": search.get("search_window_mjd") if search else None,
        "t0_values": search.get("t0_values") if search else None,
        "rm_values_km": search.get("rm_values_km") if search else None,
        "side_values": search.get("side_values") if search else None,
        "candidate_count": len(rows),
        "legacy_candidate_count": len(legacy_rows),
        "complete_search_candidate_count": len(search.get("candidates", [])) if search else 0,
        "valid_complete_return_count": search.get("valid_complete_return_count") if search else 0,
        "valid_fair_return_count": search.get("valid_fair_return_count") if search else 0,
        "best_valid_candidate": best_valid,
        "best_near_miss": best_near_miss,
        "old_legacy_candidates_all_nonreturn": bool(
            legacy is not None and legacy.get("valid_return_events") == 0
        ),
        "old_invalid_formal_fields_count": old_invalid_formal_count,
        "no_lunar_launch_window_candidates_present": False,
        "no_lunar_launch_window_note": "No dedicated M6 no-lunar launch-window result file is currently wired into this audit.",
        "event_semantics": {
            "return_vinf_defined_only_at_earth_return": True,
            "earth_return_threshold_km": search.get("search_space", {}).get("earth_return_threshold_km")
            if search
            else None,
        },
        "not_a_legacy_perihelion_vinf_search": search.get("not_a_legacy_perihelion_vinf_search") if search else None,
        "independent_spotcheck": spotcheck,
        "red_flags": red_flags,
        "candidates": rows,
    }

    json_path = RESULTS / "m6_numerical_deep_audit.json"
    csv_path = RESULTS / "m6_numerical_deep_audit.csv"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    print(f"Saved: {json_path}")
    print(f"Saved: {csv_path}")
    print(f"classification = {classification}")
    print(f"status = {status}")
    print(f"legacy candidates = {len(legacy_rows)}")
    print(f"actual candidates = {len(actual_rows)}")
    print(f"near misses = {len(near_miss_rows)}")
    if best_valid:
        print(
            f"best valid: t0={best_valid['t0_mjd']:.0f}, "
            f"return_vinf={best_valid['return_vinf_kms']}, total={best_valid['total_vinf_basis_kms']}"
        )
    if best_near_miss:
        print(
            f"best near miss: t0={best_near_miss['t0_mjd']:.0f}, "
            f"dist={best_near_miss['distance_to_earth_km']}"
        )
    if red_flags:
        print("red flags:")
        for flag in red_flags:
            print(f"  - {flag}")


if __name__ == "__main__":
    main()
