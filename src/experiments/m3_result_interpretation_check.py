"""
m3_result_interpretation_check.py
================================
Meaning check for what the current M3 result does and does not support.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "data" / "results"


def main() -> int:
    src = RESULTS / "m3_numerical_deep_audit.json"
    if not src.exists():
        raise FileNotFoundError("data/results/m3_numerical_deep_audit.json missing")
    data = json.loads(src.read_text(encoding="utf-8"))

    full_model = data["models"]["full_planetary"]
    payload = {
        "task": "M3 result interpretation check",
        "full_planetary_residual_km": full_model["heliocentric_residual_km"],
        "full_planetary_frame": full_model["frame"],
        "is_same_source": bool(data.get("not_independent_jpl_prediction")),
        "is_independent_jpl_prediction": False,
        "no_daily_horizons_reset": bool(data.get("no_daily_horizons_reset")),
        "dt_convergence_interpretation": data.get("dt_convergence_interpretation"),
        "supports": [
            "N-body integrator and force-model consistency against same-source Horizons propagation",
            "Model-hierarchy comparison from 3-body to full planetary under one shared initial-condition source",
        ],
        "does_not_support": [
            "independent ephemeris prediction accuracy",
            "a claim that 126 km is an external blind-validation error against independently sourced state histories",
        ],
        "status": "PASS_WITH_SCOPE",
    }

    out = RESULTS / "m3_result_interpretation_check.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved: {out}")
    print(f"full_planetary_residual_km = {payload['full_planetary_residual_km']}")
    print(f"status = {payload['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
