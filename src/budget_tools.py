"""
budget_tools.py
===============
Unified delta-v accounting helpers for the formal problem-statement budget:

    dv_total = dv_launch + dv_lunar_residual_or_dsm + dv_reentry

The launch term is defined from Earth's surface using the hyperbolic-excess
speed at departure. The middle term is the lunar residual for lunar-assist
cases and the DSM correction for no-lunar baselines. The reentry term is the
braking required to satisfy the v_inf <= 15 km/s mission constraint.

This module also provides lightweight normalization helpers so legacy result
rows that only stored `total_vinf_basis_kms` can be upgraded in-memory to the
formal three-segment budget without rerunning heavy searches.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from constants import GM_EARTH, R_EARTH


RETURN_VINF_LIMIT_KMS = 15.0


def surface_launch_equivalent_kms(departure_vinf_kms: float) -> float:
    """Convert departure hyperbolic excess speed into a surface-launch delta-v."""
    return math.sqrt(float(departure_vinf_kms) ** 2 + 2.0 * GM_EARTH / R_EARTH)


def return_braking_delta_v_kms(return_vinf_kms: float | None) -> float:
    if return_vinf_kms is None:
        return 0.0
    return max(0.0, float(return_vinf_kms) - RETURN_VINF_LIMIT_KMS)


def lunar_three_segment_budget(
    *,
    departure_vinf_kms: float,
    lunar_residual_kms: float,
    return_vinf_kms: float | None,
) -> dict[str, Any]:
    dv_launch = surface_launch_equivalent_kms(float(departure_vinf_kms))
    dv_lunar = float(lunar_residual_kms)
    dv_reentry = return_braking_delta_v_kms(return_vinf_kms)
    return {
        "budget_basis": "three_segment_formal",
        "dv_launch_kms": round(dv_launch, 4),
        "dv_lunar_residual_kms": round(dv_lunar, 4),
        "dv_reentry_kms": round(dv_reentry, 4),
        "dv_total_kms": round(dv_launch + dv_lunar + dv_reentry, 4),
    }


def no_lunar_three_segment_budget(
    *,
    departure_vinf_kms: float,
    dsm_delta_v_kms: float,
    return_vinf_kms: float | None,
) -> dict[str, Any]:
    dv_launch = surface_launch_equivalent_kms(float(departure_vinf_kms))
    dv_mid = float(dsm_delta_v_kms)
    dv_reentry = return_braking_delta_v_kms(return_vinf_kms)
    return {
        "budget_basis": "three_segment_formal",
        "dv_launch_kms": round(dv_launch, 4),
        "dv_midcourse_kms": round(dv_mid, 4),
        "dv_reentry_kms": round(dv_reentry, 4),
        "dv_total_kms": round(dv_launch + dv_mid + dv_reentry, 4),
    }


def saving_ratio(lunar_total_kms: float, no_lunar_total_kms: float) -> float:
    lunar_total = float(lunar_total_kms)
    no_lunar_total = float(no_lunar_total_kms)
    return (no_lunar_total - lunar_total) / no_lunar_total


def _fill_if_missing_or_none(target: dict[str, Any], key: str, value: Any) -> None:
    if key not in target or target.get(key) is None:
        target[key] = value


def ensure_lunar_row_formal_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a lunar candidate row enriched with formal budget fields."""
    enriched = dict(row)
    dep = enriched.get("departure_vinf_kms")
    ret = enriched.get("return_vinf_kms")
    lunar_residual = enriched.get("dv_lunar_residual_kms")
    if lunar_residual is None:
        lunar_residual = enriched.get("swingby_dv_kms")
    if dep is None or lunar_residual is None:
        return enriched
    budget = lunar_three_segment_budget(
        departure_vinf_kms=float(dep),
        lunar_residual_kms=float(lunar_residual),
        return_vinf_kms=None if ret is None else float(ret),
    )
    _fill_if_missing_or_none(enriched, "launch_equivalent_kms", budget["dv_launch_kms"])
    _fill_if_missing_or_none(enriched, "return_braking_kms", budget["dv_reentry_kms"])
    _fill_if_missing_or_none(enriched, "dv_launch_kms", budget["dv_launch_kms"])
    _fill_if_missing_or_none(enriched, "dv_lunar_residual_kms", budget["dv_lunar_residual_kms"])
    _fill_if_missing_or_none(enriched, "dv_reentry_kms", budget["dv_reentry_kms"])
    _fill_if_missing_or_none(enriched, "dv_total_kms", budget["dv_total_kms"])
    _fill_if_missing_or_none(enriched, "budget_basis", budget["budget_basis"])
    return enriched


def ensure_no_lunar_row_formal_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a no-lunar row enriched with formal budget fields."""
    enriched = dict(row)
    dep = enriched.get("departure_vinf_kms")
    ret = enriched.get("return_vinf_kms")
    mid = enriched.get("dv_midcourse_kms")
    if mid is None:
        mid = enriched.get("dsm_delta_v_kms")
    if dep is None or mid is None:
        return enriched
    budget = no_lunar_three_segment_budget(
        departure_vinf_kms=float(dep),
        dsm_delta_v_kms=float(mid),
        return_vinf_kms=None if ret is None else float(ret),
    )
    _fill_if_missing_or_none(enriched, "dv_launch_kms", budget["dv_launch_kms"])
    _fill_if_missing_or_none(enriched, "dv_midcourse_kms", budget["dv_midcourse_kms"])
    _fill_if_missing_or_none(enriched, "dv_reentry_kms", budget["dv_reentry_kms"])
    _fill_if_missing_or_none(enriched, "dv_total_kms", budget["dv_total_kms"])
    _fill_if_missing_or_none(enriched, "budget_basis", budget["budget_basis"])
    return enriched


def lunar_candidate_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    row = ensure_lunar_row_formal_fields(row)
    return (
        0 if row.get("fair") else 1,
        0 if row.get("valid_return_event") else 1,
        float(row.get("dv_total_kms")) if row.get("dv_total_kms") is not None else float("inf"),
        float(row.get("distance_to_earth_km")) if row.get("distance_to_earth_km") is not None else float("inf"),
        float(row.get("perihelion_error_AU")) if row.get("perihelion_error_AU") is not None else float("inf"),
        float(row.get("return_vinf_kms")) if row.get("return_vinf_kms") is not None else float("inf"),
    )


def best_lunar_candidate(rows: Iterable[dict[str, Any]], *, fair_only: bool = True) -> dict[str, Any] | None:
    normalized = [ensure_lunar_row_formal_fields(row) for row in rows]
    if fair_only:
        normalized = [row for row in normalized if row.get("fair")]
    if not normalized:
        return None
    return min(normalized, key=lunar_candidate_sort_key)
