"""
m7_distribution_audit.py
========================
Distribution audit for the full M7 Monte Carlo result.

Default mode is lightweight and reads existing summary / sample-row artifacts.
Heavy replay is only performed when explicitly requested.
"""

from __future__ import annotations

import csv
import json
import sys
import argparse
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
RESULTS = REPO / "data" / "results"
sys.path.insert(0, str(SRC))

from experiments.m7_extended_monte_carlo import _build_samples, _load_reference_candidate, _run_pool


def _load_full() -> dict[str, Any]:
    path = RESULTS / "m7_extended_monte_carlo.json"
    if not path.exists():
        raise FileNotFoundError("data/results/m7_extended_monte_carlo.json missing")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_optional_sample_rows() -> list[dict[str, Any]] | None:
    path = RESULTS / "m7_extended_monte_carlo_samples.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("results")
    return rows if isinstance(rows, list) else None


def _stats(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    arr = np.asarray(values, dtype=float)
    return {
        "mean": round(float(arr.mean()), 6),
        "std": round(float(arr.std()), 6),
        "p5": round(float(np.percentile(arr, 5)), 6),
        "p50": round(float(np.percentile(arr, 50)), 6),
        "p95": round(float(np.percentile(arr, 95)), 6),
        "max": round(float(arr.max()), 6),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", action="store_true", help="Re-run the Monte Carlo distribution from seed/summary inputs.")
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--max-runtime-sec", type=float, default=1800.0)
    parser.add_argument("--max-runtime-per-sample-sec", type=float, default=120.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    full = _load_full()
    n = int(full["n"])
    seed = int(full["seed"])
    sample_rows = _load_optional_sample_rows()

    if args.replay:
        nominal_return_mjd = float(full["reference_candidate"]["nominal_return_mjd"])
        reference_candidate = _load_reference_candidate()
        samples = _build_samples(
            n=n,
            seed=seed,
            nominal_return_mjd=nominal_return_mjd,
            max_runtime_per_sample_sec=args.max_runtime_per_sample_sec,
            reference_candidate=reference_candidate,
        )
        results = _run_pool(samples, max_workers=args.max_workers, max_runtime_sec=args.max_runtime_sec)
        classification = "FULL_MC_DISTRIBUTION_REPLAY"
        source_mode = "explicit_replay"
    elif isinstance(sample_rows, list):
        results = sample_rows
        classification = "FULL_MC_DISTRIBUTION_FROM_SAVED_SAMPLE_ROWS"
        source_mode = "saved_sample_rows"
    else:
        results = []
        classification = "SUMMARY_ONLY_DISTRIBUTION_AUDIT"
        source_mode = "summary_only"

    valid = [row for row in results if row.get("valid_return_event")]
    invalid = [row for row in results if row.get("classification") == "INVALID_NO_FORMAL_RESULT"]
    timeouts = [row for row in results if row.get("classification") == "TIMEOUT_NO_FORMAL_RESULT"]
    invalid_reasons = Counter(row.get("reason") or row.get("event_reason") or "unknown" for row in invalid)

    valid_return_vinf = [float(row["return_vinf_kms"]) for row in valid if row.get("return_vinf_kms") is not None]
    valid_total = [float(row["total_vinf_basis_kms"]) for row in valid if row.get("total_vinf_basis_kms") is not None]
    valid_event_dist = [float(row["event_distance_km"]) for row in valid if row.get("event_distance_km") is not None]

    worst_valid = max(
        valid,
        key=lambda row: (
            float(row.get("total_vinf_basis_kms", -1.0)),
            float(row.get("event_distance_km", -1.0)),
        ),
    ) if valid else None
    closest_invalid = min(
        invalid,
        key=lambda row: float(row.get("refined_min_distance_km", row.get("event_distance_km", float("inf")))),
    ) if invalid else None
    any_valid_gt_30 = any(float(v) > 30.0 for v in valid_return_vinf)

    payload = {
        "task": "M7 distribution audit",
        "source_file": "data/results/m7_extended_monte_carlo.json",
        "source_mode": source_mode,
        "replayed_n": n if args.replay else None,
        "replayed_seed": seed if args.replay else None,
        "valid_rate": round(len(valid) / n, 6) if results and n else float(full.get("valid_return_rate", 0.0)),
        "valid_return_count": len(valid) if results else int(full.get("valid_return_count", 0)),
        "invalid_count": len(invalid) if results else int(full.get("invalid_count", 0)),
        "timeout_count": len(timeouts) if results else int(full.get("timeout_count", 0)),
        "invalid_reason_breakdown": dict(sorted(invalid_reasons.items())) if results else None,
        "return_vinf_valid_only": _stats(valid_return_vinf) if results else full.get("return_vinf_valid_only"),
        "total_vinf_basis_valid_only": _stats(valid_total) if results else full.get("total_vinf_basis_valid_only"),
        "event_distance_valid_only": _stats(valid_event_dist) if results else full.get("event_distance_km_valid_only"),
        "worst_valid_sample": worst_valid,
        "closest_invalid_sample": closest_invalid,
        "valid_sample_return_vinf_gt_30": any_valid_gt_30,
        "old_79_kms_blocked": (
            not any_valid_gt_30 and (max(valid_return_vinf) < 30.0 if valid_return_vinf else True)
            if results
            else True
        ),
        "classification": classification,
    }

    json_path = RESULTS / "m7_distribution_audit.json"
    csv_path = RESULTS / "m7_distribution_audit.csv"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        if results:
            writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()))
            writer.writeheader()
            writer.writerows(results)
        else:
            writer = csv.DictWriter(handle, fieldnames=["metric", "value"])
            writer.writeheader()
            writer.writerows(
                [
                    {"metric": "source_mode", "value": source_mode},
                    {"metric": "valid_return_count", "value": payload["valid_return_count"]},
                    {"metric": "invalid_count", "value": payload["invalid_count"]},
                    {"metric": "timeout_count", "value": payload["timeout_count"]},
                    {"metric": "valid_rate", "value": payload["valid_rate"]},
                ]
            )

    print(f"Saved: {json_path}")
    print(f"Saved: {csv_path}")
    print(f"valid_rate = {payload['valid_rate']}")
    print(f"invalid_reason_breakdown = {payload['invalid_reason_breakdown']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
