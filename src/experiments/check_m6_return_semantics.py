"""Check formal M6 return-event semantics and deep-audit consistency."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
RESULTS = _REPO / "data" / "results"
ERRORS: list[str] = []


def _load(name: str) -> dict:
    path = RESULTS / name
    if not path.exists():
        ERRORS.append(f"[FAIL] {name}: missing result file")
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def check_search(search: dict) -> None:
    name = "m6_complete_return_window_search.json"
    threshold = float(search.get("search_space", {}).get("earth_return_threshold_km", 1.5e6))
    if search.get("event_semantics", {}).get("return_vinf_defined_only_at_earth_return") is not True:
        ERRORS.append(f"[FAIL] {name}: missing return-event semantics guard")

    for row in search.get("candidates", []):
        valid = bool(row.get("valid_return_event"))
        ret = row.get("return_vinf_kms")
        total = row.get("total_vinf_basis_kms")
        dist = row.get("distance_to_earth_km")
        classification = row.get("classification")
        cid = row.get("candidate_id")

        if not valid:
            if ret is not None:
                ERRORS.append(f"[FAIL] {name}: {cid} has return_vinf_kms without valid_return_event")
            if total is not None:
                ERRORS.append(f"[FAIL] {name}: {cid} has total_vinf_basis_kms without valid_return_event")
        else:
            if dist is None or float(dist) > threshold:
                ERRORS.append(
                    f"[FAIL] {name}: {cid} valid_return_event but distance_to_earth_km={dist} exceeds threshold"
                )
            if ret is None:
                ERRORS.append(f"[FAIL] {name}: {cid} valid_return_event but return_vinf_kms missing")
            if classification == "ACTUAL_RESULT" and total is None:
                ERRORS.append(f"[FAIL] {name}: {cid} ACTUAL_RESULT but total_vinf_basis_kms missing")
            if ret is not None and float(ret) > 30.0 and dist is None:
                ERRORS.append(f"[FAIL] {name}: {cid} return_vinf_kms={ret} > 30 km/s without distance check")

        if classification == "ACTUAL_RESULT" and not valid:
            ERRORS.append(f"[FAIL] {name}: {cid} classified ACTUAL_RESULT without valid Earth return")


def check_deep_audit(audit: dict) -> None:
    name = "m6_numerical_deep_audit.json"
    status = audit.get("status")
    classification = audit.get("classification")
    if status == "RED":
        ERRORS.append(f"[FAIL] {name}: status is RED")
    if classification == "FINITE_SEARCH_NEG":
        if audit.get("search_space") is None:
            ERRORS.append(f"[FAIL] {name}: FINITE_SEARCH_NEG missing search_space")
        if audit.get("best_near_miss") is None:
            ERRORS.append(f"[FAIL] {name}: FINITE_SEARCH_NEG missing best_near_miss")
    if classification == "ACTUAL_RESULT":
        best = audit.get("best_valid_candidate")
        if not best:
            ERRORS.append(f"[FAIL] {name}: ACTUAL_RESULT missing best_valid_candidate")
        elif best.get("valid_return_event") is not True:
            ERRORS.append(f"[FAIL] {name}: best_valid_candidate missing valid_return_event")

    for row in audit.get("candidates", []):
        cid = row.get("candidate_id")
        row_class = row.get("classification")
        formal = row.get("return_vinf_kms")
        legacy = row.get("legacy_return_vinf_kms")
        valid = bool(row.get("valid_return_event"))

        if row_class == "INVALID_LEGACY_EVENT":
            if formal is not None:
                ERRORS.append(f"[FAIL] {name}: legacy row {cid} leaked formal return_vinf_kms={formal}")
            if legacy is None:
                ERRORS.append(f"[FAIL] {name}: legacy row {cid} missing legacy_return_vinf_kms")
            if legacy is not None and float(legacy) >= 30.0 and valid:
                ERRORS.append(f"[FAIL] {name}: legacy high-return row {cid} unexpectedly marked valid")
        if row_class == "ACTUAL_RESULT" and not valid:
            ERRORS.append(f"[FAIL] {name}: ACTUAL_RESULT row {cid} lacks valid_return_event")
        if formal is not None and abs(float(formal) - 77.88) < 0.2:
            ERRORS.append(f"[FAIL] {name}: old invalid 77.88 km/s leaked into formal return_vinf")
        if formal is not None and float(formal) >= 79.0 and row_class != "INVALID_LEGACY_EVENT":
            ERRORS.append(f"[FAIL] {name}: high return_vinf {formal} appears outside legacy invalid rows")


def main() -> int:
    search = _load("m6_complete_return_window_search.json")
    audit = _load("m6_numerical_deep_audit.json")
    if search:
        check_search(search)
    if audit:
        check_deep_audit(audit)

    if ERRORS:
        for err in ERRORS:
            print(err)
        print(f"\n{len(ERRORS)} failure(s)")
        return 1

    print("OK: M6 return semantics checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
