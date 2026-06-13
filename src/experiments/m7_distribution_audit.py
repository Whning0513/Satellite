"""
m7_distribution_audit.py
========================
Replay-based distribution audit for the full M7 Monte Carlo result.
"""

from __future__ import annotations

import csv
import json
import sys
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


def main() -> int:
    full = _load_full()
    n = int(full["n"])
    seed = int(full["seed"])
    nominal_return_mjd = float(full["reference_candidate"]["nominal_return_mjd"])
    reference_candidate = _load_reference_candidate()
    samples = _build_samples(
        n=n,
        seed=seed,
        nominal_return_mjd=nominal_return_mjd,
        max_runtime_per_sample_sec=120.0,
        reference_candidate=reference_candidate,
    )
    results = _run_pool(samples, max_workers=1, max_runtime_sec=1800.0)

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
        "replayed_n": n,
        "replayed_seed": seed,
        "valid_rate": round(len(valid) / n, 6) if n else 0.0,
        "valid_return_count": len(valid),
        "invalid_count": len(invalid),
        "timeout_count": len(timeouts),
        "invalid_reason_breakdown": dict(sorted(invalid_reasons.items())),
        "return_vinf_valid_only": _stats(valid_return_vinf),
        "total_vinf_basis_valid_only": _stats(valid_total),
        "event_distance_valid_only": _stats(valid_event_dist),
        "worst_valid_sample": worst_valid,
        "closest_invalid_sample": closest_invalid,
        "valid_sample_return_vinf_gt_30": any_valid_gt_30,
        "old_79_kms_blocked": not any_valid_gt_30 and (max(valid_return_vinf) < 30.0 if valid_return_vinf else True),
        "classification": "FULL_MC_DISTRIBUTION_REPLAY",
    }

    json_path = RESULTS / "m7_distribution_audit.json"
    csv_path = RESULTS / "m7_distribution_audit.csv"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    print(f"Saved: {json_path}")
    print(f"Saved: {csv_path}")
    print(f"valid_rate = {payload['valid_rate']}")
    print(f"invalid_reason_breakdown = {payload['invalid_reason_breakdown']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
