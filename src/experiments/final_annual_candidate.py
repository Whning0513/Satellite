"""
final_annual_candidate.py
=========================
Select the strongest available annual legal-window candidate without silently
overstating its provenance.

Preference order:
  1. M6 daily high-accuracy verification output
  2. M5 daily full-year scan output
  3. M6 independent legal-window search
  4. M5 legal-window coarse+local-refine search

This helper is intentionally read-only: it never reruns any search.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(_REPO / "src"))

from budget_tools import best_lunar_candidate, ensure_lunar_row_formal_fields
from mission_constraints import is_launch_mjd_in_window


RESULTS = _REPO / "data" / "results"


def _load_json(name: str) -> dict[str, Any] | None:
    path = RESULTS / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _best_from_payload(
    payload: dict[str, Any],
    *,
    rows_keys: list[str],
    summary_keys: list[str],
) -> dict[str, Any] | None:
    for rows_key in rows_keys:
        rows = payload.get(rows_key, [])
        if isinstance(rows, list) and rows:
            best = best_lunar_candidate(rows, fair_only=True)
            if best is not None:
                return ensure_lunar_row_formal_fields(best)
    for summary_key in summary_keys:
        candidate = payload.get(summary_key)
        if isinstance(candidate, dict) and candidate:
            return ensure_lunar_row_formal_fields(candidate)
    return None


def _candidate_block(
    name: str,
    payload: dict[str, Any],
    *,
    rows_keys: list[str],
    summary_keys: list[str],
    selection_label: str,
) -> dict[str, Any] | None:
    candidate = _best_from_payload(payload, rows_keys=rows_keys, summary_keys=summary_keys)
    if candidate is None:
        return None
    t0_mjd = candidate.get("t0_mjd")
    if t0_mjd is None or not is_launch_mjd_in_window(float(t0_mjd)):
        return None
    return {
        "selection_label": selection_label,
        "source_file": name,
        "classification": payload.get("classification"),
        "candidate_source": payload.get("candidate_source"),
        "independent_m6_search": payload.get("independent_m6_search"),
        "source_grid_reused": payload.get("source_grid_reused"),
        "m6_interpretation": payload.get("m6_interpretation"),
        "candidate": candidate,
        "payload": payload,
    }


def load_final_annual_candidate() -> dict[str, Any]:
    candidates = [
        (
            "m6_legal_window_daily_verify.json",
            dict(
                rows_keys=["verified_candidates", "candidates"],
                summary_keys=["best_verified_candidate", "best_valid_candidate"],
                selection_label="daily_verified_annual_candidate",
            ),
        ),
        (
            "m5_legal_window_daily_scan.json",
            dict(
                rows_keys=["search_rows"],
                summary_keys=["best_lunar_candidate"],
                selection_label="daily_scan_annual_candidate",
            ),
        ),
        (
            "m6_independent_window_search.json",
            dict(
                rows_keys=["candidates"],
                summary_keys=["best_valid_candidate"],
                selection_label="independent_annual_candidate",
            ),
        ),
        (
            "m5_legal_window_search.json",
            dict(
                rows_keys=["search_rows"],
                summary_keys=["best_lunar_candidate"],
                selection_label="coarse_refine_annual_candidate",
            ),
        ),
    ]
    for name, spec in candidates:
        payload = _load_json(name)
        if payload is None:
            continue
        block = _candidate_block(name, payload, **spec)
        if block is not None:
            return block
    return {
        "selection_label": "built_in_fallback",
        "source_file": None,
        "classification": "FALLBACK",
        "candidate_source": None,
        "independent_m6_search": None,
        "source_grid_reused": None,
        "m6_interpretation": None,
        "candidate": {
            "t0_mjd": 61065.0,
            "side": "trailing",
            "r_m_km": 1837.4,
            "return_event_mjd": 61431.12,
        },
        "payload": {},
    }

