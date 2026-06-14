"""
m7_timeout_diagnosis.py
=======================
Timeout diagnosis for the current M7 full Monte Carlo result.

Modes:
  - aggregate-only when only summary JSON exists
  - sample-level when saved sample rows are available
  - replay-aware when timeout replay results are available
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


def _load_optional_rows() -> list[dict] | None:
    path = RESULTS / "m7_extended_monte_carlo_samples.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("results")
    return rows if isinstance(rows, list) else None


def _compute_timeout_reason_breakdown(full: dict, sample_rows: list[dict] | None) -> dict:
    if isinstance(full.get("timeout_reason_breakdown"), dict) and full["timeout_reason_breakdown"]:
        return dict(full["timeout_reason_breakdown"])
    if isinstance(sample_rows, list):
        breakdown: dict[str, int] = {}
        for row in sample_rows:
            if row.get("classification") != "TIMEOUT_NO_FORMAL_RESULT":
                continue
            reason = str(row.get("reason") or "unknown")
            breakdown[reason] = int(breakdown.get(reason, 0)) + 1
        return dict(sorted(breakdown.items()))
    timeout_count = int(full.get("timeout_count", 0) or 0)
    if timeout_count <= 0:
        return {}
    return {"aggregate_timeout_without_sample_rows": timeout_count}


def _backfill_summary_fields(full: dict, sample_rows: list[dict] | None) -> bool:
    changed = False
    sample_rows_path = RESULTS / "m7_extended_monte_carlo_samples.json"
    replay_manifest_path = RESULTS / "m7_timeout_replay_manifest.json"
    has_sample_rows = isinstance(sample_rows, list)

    desired_saved = has_sample_rows
    if full.get("sample_rows_saved") != desired_saved:
        full["sample_rows_saved"] = desired_saved
        changed = True

    desired_sample_rows_file = (
        "data/results/m7_extended_monte_carlo_samples.json" if has_sample_rows else None
    )
    if full.get("sample_rows_file") != desired_sample_rows_file:
        full["sample_rows_file"] = desired_sample_rows_file
        changed = True

    desired_timeout_manifest = (
        "data/results/m7_timeout_replay_manifest.json"
        if replay_manifest_path.exists()
        else None
    )
    if full.get("timeout_replay_manifest_file") != desired_timeout_manifest:
        full["timeout_replay_manifest_file"] = desired_timeout_manifest
        changed = True

    desired_breakdown = _compute_timeout_reason_breakdown(full, sample_rows)
    if full.get("timeout_reason_breakdown") != desired_breakdown:
        full["timeout_reason_breakdown"] = desired_breakdown
        changed = True

    # Keep file paths synchronized with actual lightweight artifacts if they exist.
    if has_sample_rows and not sample_rows_path.exists():
        full["sample_rows_saved"] = False
        full["sample_rows_file"] = None
        changed = True

    return changed


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

    sample_rows = _load_optional_rows()
    if _backfill_summary_fields(full, sample_rows):
        (RESULTS / "m7_extended_monte_carlo.json").write_text(
            json.dumps(full, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    replay = _load("m7_timeout_replay.json")
    sample_level_results_available = isinstance(sample_rows, list)
    timeout_reason_breakdown: dict[str, int | str] = {}
    timeout_parameter_summary = None
    replay_summary = None

    if sample_level_results_available:
        timeout_rows = [row for row in sample_rows if row.get("classification") == "TIMEOUT_NO_FORMAL_RESULT"]
        for row in timeout_rows:
            reason = str(row.get("reason") or "unknown")
            timeout_reason_breakdown[reason] = int(timeout_reason_breakdown.get(reason, 0)) + 1
        if timeout_rows:
            t0_vals = [float(row["t0_mjd"]) for row in timeout_rows if row.get("t0_mjd") is not None]
            rm_vals = [float(row["r_m_km"]) for row in timeout_rows if row.get("r_m_km") is not None]
            rp_vals = [float(row["rp_target_au"]) for row in timeout_rows if row.get("rp_target_au") is not None]
            timeout_parameter_summary = {
                "t0_mjd_min": round(min(t0_vals), 6) if t0_vals else None,
                "t0_mjd_max": round(max(t0_vals), 6) if t0_vals else None,
                "r_m_km_min": round(min(rm_vals), 3) if rm_vals else None,
                "r_m_km_max": round(max(rm_vals), 3) if rm_vals else None,
                "rp_target_au_min": round(min(rp_vals), 6) if rp_vals else None,
                "rp_target_au_max": round(max(rp_vals), 6) if rp_vals else None,
            }
    else:
        timeout_reason_breakdown = _compute_timeout_reason_breakdown(full, sample_rows)

    if replay is not None:
        replay_results = replay.get("results", [])
        replay_valid = sum(1 for row in replay_results if row.get("valid_return_event"))
        replay_invalid = sum(1 for row in replay_results if row.get("classification") == "INVALID_NO_FORMAL_RESULT")
        replay_timeout = sum(1 for row in replay_results if row.get("classification") == "TIMEOUT_NO_FORMAL_RESULT")
        replay_summary = {
            "selected_timeout_samples": replay.get("selected_timeout_samples"),
            "replay_valid_count": replay_valid,
            "replay_invalid_count": replay_invalid,
            "replay_timeout_count": replay_timeout,
        }

    interpretations = [
        "timeout_count must not be interpreted as physical non-return count by default.",
        "Trajectory propagation remains the dominant cost in the current profile, so runtime budget is a real contributor.",
        "Only saved sample rows or timeout replay can distinguish search-budget failure from true dynamical non-return.",
    ]
    if sample_level_results_available:
        interpretations.append("Per-sample timeout rows are available, so timeout reasons and parameter concentration can now be inspected directly.")
    else:
        interpretations.append("Current diagnosis is aggregate-only because no saved per-sample rows were found.")
    if replay_summary is not None:
        interpretations.append("Timeout replay results are available and should be preferred over aggregate-only interpretation.")
    else:
        interpretations.append("No timeout replay results were found yet.")

    if replay_summary is not None and replay_summary["replay_valid_count"] > 0:
        timeout_conclusion = "TIMEOUTS_INCLUDE_POTENTIAL_TRUE_RETURNS_REPLAY_CONFIRMED"
    elif sample_level_results_available and propagation_fraction is not None and propagation_fraction >= 0.85:
        timeout_conclusion = "TIMEOUTS_LIKELY_MIXED_SEARCH_OR_RUNTIME_LIMIT_NOT_PHYSICAL_INVALID"
    elif propagation_fraction is not None and propagation_fraction >= 0.85:
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
        "timeout_parameter_summary": timeout_parameter_summary,
        "replay_summary": replay_summary,
        "timeout_conclusion": timeout_conclusion,
        "robustness_claim_allowed": False if replay_summary is None else replay_summary["replay_valid_count"] == 0,
        "classification": (
            "SAMPLE_LEVEL_TIMEOUT_DIAGNOSIS"
            if sample_level_results_available and replay_summary is None
            else "REPLAY_AWARE_TIMEOUT_DIAGNOSIS"
            if replay_summary is not None
            else "AGGREGATE_ONLY_TIMEOUT_DIAGNOSIS_PENDING_SAMPLE_LEVEL_REPLAY"
        ),
        "interpretations": interpretations,
        "recommended_next_step": (
            "If stronger M7 closure is needed, run the full Monte Carlo with --save-sample-rows and replay a timeout subset with extended runtime/search window."
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
