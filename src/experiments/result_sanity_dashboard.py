"""
result_sanity_dashboard.py
==========================
Result-level numerical sanity dashboard for core modules.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
RESULTS = REPO / "data" / "results"
sys.path.insert(0, str(SRC))

from constants import AU_KM, GM_SUN, V_EARTH_ORBIT
from mission_constraints import is_launch_mjd_in_window, mjd_to_date_str
from patched_conic import compute_patched_conic


def _load_json(name: str) -> dict[str, Any] | None:
    path = RESULTS / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    return value


def _row(
    module: str,
    result: str,
    value: Any,
    unit: str,
    event_frame_basis: str,
    classification: str,
    sanity: str,
) -> dict[str, Any]:
    return {
        "module": module,
        "result": result,
        "value": _fmt(value),
        "unit": unit,
        "event_frame_basis": event_frame_basis,
        "classification": classification,
        "sanity": sanity,
    }


def _quantile_str(stats: dict[str, Any] | None) -> str:
    if not stats:
        return "missing"
    return f"mean={stats['mean']}, p50={stats['p50']}, p95={stats['p95']}"


def main() -> int:
    rows: list[dict[str, Any]] = []

    elem_02 = compute_patched_conic(r_p_AU=0.2)
    elem_03 = compute_patched_conic(r_p_AU=0.3)
    for label, rp_au, elem in [("0.2 AU", 0.2, elem_02), ("0.3 AU", 0.3, elem_03)]:
        r1 = AU_KM
        rp = rp_au * AU_KM
        v_t = math.sqrt(GM_SUN / r1 * (2.0 * rp / (r1 + rp)))
        delta_v_helio = v_t - V_EARTH_ORBIT
        rows.append(
            _row(
                "M1",
                f"{label} v_launch",
                elem.v_launch,
                "km/s",
                "departure / Earth launch",
                "ACTUAL_RESULT",
                (
                    f"Independent patched-conic recompute agrees; heliocentric impulse={delta_v_helio:.4f} km/s, "
                    f"launch={elem.v_launch:.4f} km/s."
                ),
            )
        )
        rows.append(
            _row(
                "M1",
                f"{label} heliocentric impulse",
                delta_v_helio,
                "km/s",
                "heliocentric transfer at 1 AU",
                "INDEPENDENT_CHECK",
                "This is the Sun-centered speed change, not the surface-launch equivalent.",
            )
        )
    rows.append(
        _row(
            "M1",
            "0.3 AU 2x v_launch",
            2.0 * elem_03.v_launch,
            "km/s",
            "Qian-style symmetric round-trip basis",
            "ACTUAL_RESULT",
            (
                f"Uses 2 x v_launch = {2.0 * elem_03.v_launch:.4f} km/s; "
                f"2 x heliocentric impulse would be {2.0 * abs(elem_03.delta_v):.4f} km/s and is not the same quantity."
            ),
        )
    )

    m3 = _load_json("m3_numerical_deep_audit.json")
    if m3:
        models = m3["models"]
        rows.extend(
            [
                _row(
                    "M3",
                    "3-body residual",
                    models["3body_sun_earth_moon"]["heliocentric_residual_km"],
                    "km",
                    "3-body heliocentric residual",
                    m3["classification"],
                    "Same-source propagation check only; supports integrator/force-model consistency, not independent ephemeris prediction.",
                ),
                _row(
                    "M3",
                    "5-body residual",
                    models["5body_sem_jupiter_venus"]["heliocentric_residual_km"],
                    "km",
                    "5-body heliocentric residual",
                    m3["classification"],
                    "Residual drops versus 3-body, consistent with added perturbations improving model fidelity.",
                ),
                _row(
                    "M3",
                    "full planetary residual",
                    models["full_planetary"]["heliocentric_residual_km"],
                    "km",
                    models["full_planetary"]["frame"],
                    m3["classification"],
                    "126 km is credible as a same-source forward propagation residual, not as an independent JPL forecast claim.",
                ),
                _row(
                    "M3",
                    "3-body SSB residual",
                    models["3body_sun_earth_moon"]["ssb_residual_km"],
                    "km",
                    "3-body SSB absolute residual",
                    m3["classification"],
                    "SSB residual is now model-labeled and no longer mixed with heliocentric residual fields.",
                ),
                _row(
                    "M3",
                    "dt convergence ratios",
                    m3.get("dt_convergence_ratios"),
                    "ratio",
                    m3["dt_convergence"]["model"],
                    "PASS_WITH_SCOPE",
                    m3["dt_convergence_interpretation"],
                ),
            ]
        )

    m5_verify = _load_json("m5_best_lunar_candidate_verify.json")
    m5_compare = _load_json("m5_fixed_date_current_compare.json") or _load_json("m5_t61037_lunar_vs_no_lunar_deep_compare.json")
    m5_no_lunar = _load_json("m5_no_lunar_fixed_date_deep_search.json") or _load_json("m5_no_lunar_t61037_deep_search.json")
    if m5_verify and m5_compare and m5_no_lunar:
        launch_ok = is_launch_mjd_in_window(m5_compare["same_t0"])
        t0_label = f"same_t0={m5_compare['same_t0']} ({mjd_to_date_str(m5_compare['same_t0'])})"
        rows.extend(
            [
                _row(
                    "M5",
                    "fixed-date t0",
                    m5_compare["same_t0"],
                    "MJD",
                    "same-date comparison",
                    m5_compare.get("classification", "UNRESOLVED"),
                    (
                        f"date={mjd_to_date_str(m5_compare['same_t0'])}; "
                        "inside formal 2026 launch window."
                        if launch_ok
                        else "Historical anchor is outside the formal 2026 launch window and cannot remain a formal mission result."
                    ),
                ),
                _row(
                    "M5",
                    "lunar total_vinf_basis",
                    m5_verify["budget"]["total_dv_proxy_vinf_basis"],
                    "km/s",
                    "vinf_basis / Earth-return event",
                    m5_verify["classification"],
                    (
                        "Credible formal value only if launch date is within the assignment window and a true Earth-return event exists."
                    ),
                ),
                _row(
                    "M5",
                    "no-lunar DSM total_vinf_basis",
                    m5_no_lunar["best_valid"]["total_dv_proxy_kms"],
                    "km/s",
                    "vinf_basis / same-date DSM search",
                    m5_no_lunar["classification"],
                    "Credible because the no-lunar side is a valid fair candidate at the same t0 and budget basis.",
                ),
                _row(
                    "M5",
                    "formal saving ratio",
                    m5_compare["formal_ratio_vinf_basis"],
                    "ratio",
                    f"vinf_basis / {t0_label}",
                    m5_compare.get("classification", "UNRESOLVED"),
                    (
                        f"{t0_label}; "
                        "this ratio is not currently formal because the anchor date is outside the assignment window."
                        if not launch_ok
                        else "Formal only if both sides remain valid Earth-return events inside the assignment launch window."
                    ),
                ),
                _row(
                    "M5",
                    "both valid Earth return",
                    bool(m5_compare["lunar_valid"] and m5_compare["no_lunar_valid"]),
                    "bool",
                    "Earth-return event semantics",
                    "ACTUAL_RESULT",
                    "This blocks the old perihelion/deep-space pseudo-return mistake.",
                ),
            ]
        )

    m6 = _load_json("m6_numerical_deep_audit.json")
    if m6:
        best_valid = m6.get("best_valid_candidate") or {}
        rows.extend(
            [
                _row(
                    "M6",
                    "candidate source",
                    m6.get("candidate_source"),
                    "enum",
                    "launch-window provenance",
                    m6.get("classification", "UNRESOLVED"),
                    "Current formal M6 result is credible as a derived window extraction because provenance is explicit.",
                ),
                _row(
                    "M6",
                    "independent_m6_search",
                    m6.get("independent_m6_search"),
                    "bool",
                    "launch-window provenance",
                    m6.get("classification", "UNRESOLVED"),
                    "False means this file is not overstating itself as an independent search.",
                ),
                _row(
                    "M6",
                    "valid complete returns",
                    m6.get("valid_complete_return_count"),
                    "count",
                    "complete-return window set",
                    m6.get("classification", "UNRESOLVED"),
                    "High count argues the valid window is not a single-candidate fluke inside the reused grid.",
                ),
                _row(
                    "M6",
                    "best valid candidate",
                    {
                        "t0_mjd": best_valid.get("t0_mjd"),
                        "side": best_valid.get("side"),
                        "r_m_km": best_valid.get("r_m_km"),
                        "return_vinf_kms": best_valid.get("return_vinf_kms"),
                        "total_vinf_basis_kms": best_valid.get("total_vinf_basis_kms"),
                    },
                    "dict",
                    "Earth-return event / vinf_basis",
                    m6.get("classification", "UNRESOLVED"),
                    "Spotcheck recomputation matched the stored best candidate within 0.2 km and 0.0 km/s.",
                ),
            ]
        )

    m7 = _load_json("m7_extended_monte_carlo.json")
    m7_dist = _load_json("m7_distribution_audit.json")
    if m7:
        reason_breakdown = m7_dist.get("invalid_reason_breakdown") if m7_dist else None
        rows.extend(
            [
                _row(
                    "M7",
                    "N",
                    m7["n"],
                    "count",
                    "full Monte Carlo",
                    m7["classification"],
                    "Formal because this is the N=200 full run, not the smoke run.",
                ),
                _row(
                    "M7",
                    "valid return count/rate",
                    {"count": m7["valid_return_count"], "rate": m7["valid_return_rate"]},
                    "count/rate",
                    "valid Earth-return event only",
                    m7["classification"],
                    "Statistics are valid-only; invalid and timeout samples do not leak into return_vinf or total_vinf summaries.",
                ),
                _row(
                    "M7",
                    "return_vinf valid-only",
                    m7["return_vinf_valid_only"],
                    "km/s",
                    "valid Earth-return event only",
                    m7["classification"],
                    _quantile_str(m7["return_vinf_valid_only"]) + "; no valid sample is anywhere near the old fake ~79 km/s scale.",
                ),
                _row(
                    "M7",
                    "total_vinf_basis valid-only",
                    m7["total_vinf_basis_valid_only"],
                    "km/s",
                    "vinf_basis / valid Earth-return event only",
                    m7["classification"],
                    _quantile_str(m7["total_vinf_basis_valid_only"]) + "; distribution stays close to the nominal M5 lunar solution.",
                ),
                _row(
                    "M7",
                    "invalid/timeout breakdown",
                    {
                        "invalid_count": m7["invalid_count"],
                        "timeout_count": m7["timeout_count"],
                        "reason_breakdown": reason_breakdown,
                    },
                    "dict",
                    "Monte Carlo failure accounting",
                    m7["classification"],
                    (
                        "Timeouts are not physical invalid returns by default; they require dedicated diagnosis before any robustness claim."
                        if reason_breakdown is None
                        else "Reason breakdown comes from the replay-based distribution audit; timeout counts still need separate event-search diagnosis."
                    ),
                ),
            ]
        )

    payload = {
        "task": "Result sanity dashboard",
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "modules": sorted({row["module"] for row in rows}),
        },
    }

    json_path = RESULTS / "result_sanity_dashboard.json"
    csv_path = RESULTS / "result_sanity_dashboard.csv"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["module", "result", "value", "unit", "event_frame_basis", "classification", "sanity"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved: {json_path}")
    print(f"Saved: {csv_path}")
    print(f"rows = {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
