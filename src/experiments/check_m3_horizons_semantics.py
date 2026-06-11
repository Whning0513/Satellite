"""Check M3 Horizons semantics: no daily reset, same-source scope, frames, dt metadata."""

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


def main() -> int:
    data = _load("m3_numerical_deep_audit.json")
    if not data:
        return 1

    if data.get("no_daily_horizons_reset") is not True:
        ERRORS.append("[FAIL] m3_numerical_deep_audit.json: no_daily_horizons_reset must be true")
    if data.get("uses_day0_initial_condition_only") is not True:
        ERRORS.append("[FAIL] m3_numerical_deep_audit.json: uses_day0_initial_condition_only must be true")
    if data.get("classification") == "INDEPENDENT_JPL_VALIDATION":
        ERRORS.append("[FAIL] m3_numerical_deep_audit.json: classification must not claim independent JPL validation")
    if data.get("classification") != "SAME_SOURCE_PROPAGATION_CHECK":
        ERRORS.append("[FAIL] m3_numerical_deep_audit.json: classification must be SAME_SOURCE_PROPAGATION_CHECK")
    if data.get("not_independent_jpl_prediction") is not True:
        ERRORS.append("[FAIL] m3_numerical_deep_audit.json: not_independent_jpl_prediction must be true")

    for key in ["residual_3body_km", "residual_5body_km", "residual_full_planetary_km", "ssb_absolute_residual_km", "heliocentric_residual_km"]:
        if data.get(key) is None:
            ERRORS.append(f"[FAIL] m3_numerical_deep_audit.json: missing {key}")

    frames = data.get("frame_definitions", {})
    if "ssb_absolute_residual_km" not in frames or "heliocentric_residual_km" not in frames:
        ERRORS.append("[FAIL] m3_numerical_deep_audit.json: missing frame definitions")

    dt_convergence = data.get("dt_convergence")
    if not isinstance(dt_convergence, list) or len(dt_convergence) < 3:
        ERRORS.append("[FAIL] m3_numerical_deep_audit.json: dt_convergence must contain at least 3 rows")
    else:
        required_dts = {1800, 900, 450}
        present = {int(row.get("dt_sec")) for row in dt_convergence if row.get("dt_sec") is not None}
        if not required_dts.issubset(present):
            ERRORS.append(f"[FAIL] m3_numerical_deep_audit.json: dt_convergence missing required dt values, got {sorted(present)}")
        for row in dt_convergence:
            if row.get("residual_km") is None:
                ERRORS.append("[FAIL] m3_numerical_deep_audit.json: dt_convergence row missing residual_km")
            if row.get("frame") is None:
                ERRORS.append("[FAIL] m3_numerical_deep_audit.json: dt_convergence row missing frame")

    if ERRORS:
        for err in ERRORS:
            print(err)
        print(f"\n{len(ERRORS)} failure(s)")
        return 1

    print("OK: M3 Horizons semantics checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
