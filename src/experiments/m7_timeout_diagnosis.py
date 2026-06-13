"""
m7_timeout_diagnosis.py
=======================
Lightweight timeout diagnosis for the current M7 full Monte Carlo result.

This script intentionally avoids rerunning the heavy N=200 Monte Carlo.
It diagnoses only what can be supported by the saved aggregate outputs.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "data" / "results"


def _load(name: str) -> dict | None:
    path = RESULTS / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    full = _load("m7_extended_monte_carlo.json")
    smoke = _load("m7_extended_monte_carlo_smoke.json")
    if full is None:
        raise FileNotFoundError("data/results/m7_extended_monte_carlo.json missing")

    n = int(full["n"])
    valid = int(full["valid_return_count"])
    invalid = int(full["invalid_count"])
    timeout = int(full["timeout_count"])
    profile = full.get("profile", {})
    semantics = full.get("event_semantics", {})

    timeout_rate = round(timeout / n, 6) if n else 0.0
    invalid_rate = round(invalid / n, 6) if n else 0.0
    valid_rate = round(valid / n, 6) if n else 0.0

    smoke_summary = None
    if smoke is not None:
        smoke_n = int(smoke["n"])
        smoke_summary = {
            "n": smoke_n,
            "valid_return_count": int(smoke["valid_return_count"]),
            "invalid_count": int(smoke["invalid_count"]),
            "timeout_count": int(smoke["timeout_count"]),
            "valid_return_rate": round(float(smoke["valid_return_rate"]), 6),
        }

    time_per_sample_mean = float(profile.get("time_per_sample_mean_sec", 0.0) or 0.0)
    time_per_sample_p95 = float(profile.get("time_per_sample_p95_sec", 0.0) or 0.0)
    time_in_propagation = float(profile.get("time_in_propagation_sec", 0.0) or 0.0)
    time_in_event_search = float(profile.get("time_in_event_search_sec", 0.0) or 0.0)
    propagation_fraction = (
        round(time_in_propagation / max(time_in_propagation + time_in_event_search, 1e-12), 6)
        if (time_in_propagation + time_in_event_search) > 0
        else None
    )

    sample_level_results_available = False
    timeout_reason_breakdown = {
        "timeout_before_event_search": "unknown_count_without_sample_rows",
        "timeout_after_event_search": "unknown_count_without_sample_rows",
        "future_timeout": "unknown_count_without_sample_rows",
    }

    interpretations = [
        "Current full JSON contains aggregate statistics only; it does not retain per-sample rows for timeout reclassification.",
        "Therefore, timeout_count must not be interpreted as physical non-return count.",
        "Full-run profiling points to trajectory_propagation as the dominant cost, so many timeouts may be compute-budget or search-budget limited rather than dynamically impossible.",
        "The smoke run reached timeout_count=0 at N=20, which supports the view that at least part of the full-run degradation is scaling/runtime related.",
        "A strong timeout diagnosis would require rerunning with saved per-sample rows or targeted timeout replay; that has not been done here.",
    ]

    if propagation_fraction is not None and propagation_fraction >= 0.85:
        timeout_conclusion = "TIMEOUTS_LIKELY_MIXED_SEARCH_OR_RUNTIME_LIMIT_NOT_PHYSICAL_INVALID"
    else:
        timeout_conclusion = "TIMEOUT_MEANING_UNRESOLVED_AGGREGATE_ONLY"

    payload = {
        "task": "M7 timeout diagnosis",
        "source_file": "data/results/m7_extended_monte_carlo.json",
        "n": n,
        "valid_return_count": valid,
        "invalid_count": invalid,
        "timeout_count": timeout,
        "valid_return_rate": valid_rate,
        "invalid_rate": invalid_rate,
        "timeout_rate": timeout_rate,
        "sample_level_results_available": sample_level_results_available,
        "full_profile_summary": {
            "time_per_sample_mean_sec": round(time_per_sample_mean, 4),
            "time_per_sample_p95_sec": round(time_per_sample_p95, 4),
            "time_in_propagation_sec": round(time_in_propagation, 4),
            "time_in_event_search_sec": round(time_in_event_search, 4),
            "propagation_fraction": propagation_fraction,
            "bottleneck_guess": profile.get("bottleneck_guess"),
            "slowest_sample_reason": profile.get("slowest_sample_reason"),
        },
        "event_semantics": semantics,
        "smoke_reference": smoke_summary,
        "timeout_reason_breakdown": timeout_reason_breakdown,
        "timeout_conclusion": timeout_conclusion,
        "robustness_claim_allowed": False,
        "classification": "AGGREGATE_ONLY_TIMEOUT_DIAGNOSIS_PENDING_SAMPLE_LEVEL_REPLAY",
        "interpretations": interpretations,
        "recommended_next_step": (
            "If stronger M7 closure is needed, rerun Monte Carlo with saved per-sample rows and replay a timeout subset with extended runtime/search window."
        ),
    }

    json_path = RESULTS / "m7_timeout_diagnosis.json"
    csv_path = RESULTS / "m7_timeout_diagnosis.csv"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    csv_rows = [
        {"metric": "valid_return_count", "value": valid},
        {"metric": "invalid_count", "value": invalid},
        {"metric": "timeout_count", "value": timeout},
        {"metric": "valid_return_rate", "value": valid_rate},
        {"metric": "invalid_rate", "value": invalid_rate},
        {"metric": "timeout_rate", "value": timeout_rate},
        {"metric": "time_per_sample_mean_sec", "value": round(time_per_sample_mean, 4)},
        {"metric": "time_per_sample_p95_sec", "value": round(time_per_sample_p95, 4)},
        {"metric": "time_in_propagation_sec", "value": round(time_in_propagation, 4)},
        {"metric": "time_in_event_search_sec", "value": round(time_in_event_search, 4)},
        {"metric": "propagation_fraction", "value": propagation_fraction},
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "value"])
        writer.writeheader()
        writer.writerows(csv_rows)

    print(f"Saved: {json_path}")
    print(f"Saved: {csv_path}")
    print(f"timeout_rate = {timeout_rate}")
    print(f"classification = {payload['classification']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
