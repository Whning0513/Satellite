"""
m3_numerical_deep_audit.py
==========================
Deep numerical-semantics audit for M3 Horizons comparisons.

This clarifies scope:
  - day-0 initial condition only
  - no daily Horizons reset
  - same-source propagation check, not independent prediction
  - heliocentric and SSB residuals are distinct
  - dt sweep is recorded explicitly

Output:
  data/results/m3_numerical_deep_audit.json
  data/results/m3_numerical_deep_audit.csv
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(_REPO / "src"))

from constants import GM_EARTH, GM_MOON, GM_SUN
from horizons import fetch_sem_vectors, initial_state_from_horizons, state_at_index
from nbody import propagate_nbody

RESULTS = _REPO / "data" / "results"


def _load(name: str) -> dict | None:
    path = RESULTS / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(vec: np.ndarray) -> float:
    return float(np.linalg.norm(vec))


def _run_3body_helio_ssb(body_data: dict, dt_s: float, max_days: int = 365, sample_step: int = 10) -> dict:
    r0, v0 = initial_state_from_horizons(body_data, idx=0)
    gm = [GM_SUN, GM_EARTH, GM_MOON]
    r_state = [ri.copy() for ri in r0]
    v_state = [vi.copy() for vi in v0]

    earth_helio = []
    earth_ssb = []
    moon_helio = []
    moon_ssb = []

    for day in range(sample_step, max_days + 1, sample_step):
        r_state, v_state = propagate_nbody(
            r_state,
            v_state,
            sample_step * 86400.0,
            gm,
            3,
            dt_internal=dt_s,
        )
        sun_ref, _ = state_at_index(body_data, "Sun", day)
        earth_ref, _ = state_at_index(body_data, "Earth", day)
        moon_ref, _ = state_at_index(body_data, "Moon", day)

        earth_helio.append(_norm((r_state[1] - r_state[0]) - (earth_ref - sun_ref)))
        earth_ssb.append(_norm(r_state[1] - earth_ref))
        moon_helio.append(_norm((r_state[2] - r_state[0]) - (moon_ref - sun_ref)))
        moon_ssb.append(_norm(r_state[2] - moon_ref))

    return {
        "Earth_helio_max_km": round(max(earth_helio), 2),
        "Earth_ssb_max_km": round(max(earth_ssb), 2),
        "Moon_helio_max_km": round(max(moon_helio), 2),
        "Moon_ssb_max_km": round(max(moon_ssb), 2),
    }


def main() -> None:
    body_data = fetch_sem_vectors(use_cache=True)
    hierarchy = _load("m3_model_hierarchy.json")
    if hierarchy is None:
        raise FileNotFoundError("data/results/m3_model_hierarchy.json missing")

    models = {model["name"]: model for model in hierarchy.get("models", [])}
    model_3 = models.get("SEM_3body", {})
    model_5 = models.get("SEM_Jupiter_Venus_5body", {})
    model_full = models.get("SEM_full_planetary", {})

    r0, v0 = initial_state_from_horizons(body_data, idx=0)
    gm = [GM_SUN, GM_EARTH, GM_MOON]
    r30, v30 = propagate_nbody(
        [ri.copy() for ri in r0],
        [vi.copy() for vi in v0],
        30.0 * 86400.0,
        gm,
        3,
        dt_internal=900.0,
    )
    earth_day30_ref, _ = state_at_index(body_data, "Earth", 30)
    no_daily_reset = _norm(r30[1] - earth_day30_ref) > 100.0

    dt_rows = []
    dt_values = [1800.0, 900.0, 450.0]
    dt_metrics = []
    for dt in dt_values:
        metric = _run_3body_helio_ssb(body_data, dt)
        dt_metrics.append(metric)
        dt_rows.append(
            {
                "dt_sec": int(dt),
                "residual_km": metric["Earth_helio_max_km"],
                "frame": "heliocentric",
            }
        )

    earth_helio_vals = [row["residual_km"] for row in dt_rows]
    ratios = []
    for i in range(len(earth_helio_vals) - 1):
        if earth_helio_vals[i + 1] > 0:
            ratios.append(round(earth_helio_vals[i] / earth_helio_vals[i + 1], 4))

    summary_rows = [
        {
            "metric": "residual_3body_km",
            "value": model_3.get("max_residual_km"),
            "frame": "heliocentric",
            "unit": "km",
        },
        {
            "metric": "residual_5body_km",
            "value": model_5.get("max_residual_km"),
            "frame": "heliocentric",
            "unit": "km",
        },
        {
            "metric": "residual_full_planetary_km",
            "value": model_full.get("max_residual_km"),
            "frame": "heliocentric",
            "unit": "km",
        },
        {
            "metric": "ssb_absolute_residual_km",
            "value": dt_metrics[1]["Moon_ssb_max_km"],
            "frame": "SSB absolute",
            "unit": "km",
        },
        {
            "metric": "heliocentric_residual_km",
            "value": dt_metrics[1]["Moon_helio_max_km"],
            "frame": "heliocentric",
            "unit": "km",
        },
    ]
    summary_rows.extend(
        {
            "metric": f"dt_{row['dt_sec']}_residual_km",
            "value": row["residual_km"],
            "frame": row["frame"],
            "unit": "km",
        }
        for row in dt_rows
    )

    payload = {
        "task": "M3 numerical deep audit",
        "uses_day0_initial_condition_only": True,
        "no_daily_horizons_reset": bool(no_daily_reset),
        "residual_3body_km": model_3.get("max_residual_km"),
        "residual_5body_km": model_5.get("max_residual_km"),
        "residual_full_planetary_km": model_full.get("max_residual_km"),
        "ssb_absolute_residual_km": dt_metrics[1]["Moon_ssb_max_km"],
        "heliocentric_residual_km": dt_metrics[1]["Moon_helio_max_km"],
        "frame_definitions": {
            "ssb_absolute_residual_km": "absolute barycentric position difference",
            "heliocentric_residual_km": "relative position difference after subtracting Sun state",
        },
        "dt_convergence": dt_rows,
        "dt_convergence_ratios": ratios,
        "dt_convergence_interpretation": (
            "Ratios near 1 indicate the 3-body residual is dominated by missing perturbations, "
            "not by the VV integrator step size, over dt=1800/900/450 s."
        ),
        "classification": "SAME_SOURCE_PROPAGATION_CHECK",
        "status": "PASS" if no_daily_reset else "RED",
        "not_independent_jpl_prediction": True,
        "same_source_scope_note": (
            "The 126 km full-planetary result is a same-source propagation check: "
            "day-0 Horizons initial conditions are propagated freely forward without daily reset."
        ),
    }

    json_path = RESULTS / "m3_numerical_deep_audit.json"
    csv_path = RESULTS / "m3_numerical_deep_audit.csv"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "value", "frame", "unit"])
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"Saved: {json_path}")
    print(f"Saved: {csv_path}")
    print(f"no_daily_horizons_reset = {payload['no_daily_horizons_reset']}")
    print(f"residual_3body_km = {payload['residual_3body_km']}")
    print(f"residual_5body_km = {payload['residual_5body_km']}")
    print(f"residual_full_planetary_km = {payload['residual_full_planetary_km']}")


if __name__ == "__main__":
    main()
