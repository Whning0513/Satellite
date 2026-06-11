"""Checks M7 Monte Carlo return-event semantics for smoke/full outputs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
RESULTS = _REPO / "data" / "results"

FILES = [
    RESULTS / "m7_extended_monte_carlo_smoke.json",
    RESULTS / "m7_extended_monte_carlo.json",
    RESULTS / "m7_extended_monte_carlo_profile.json",
]

ERRORS: list[str] = []


def _check_file(path: Path) -> None:
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    name = path.name
    classification = data.get("classification")
    n = data.get("n")
    semantics = data.get("event_semantics", {})

    if not semantics.get("return_vinf_defined_only_at_earth_return"):
        ERRORS.append(f"[FAIL] {name}: missing return-event semantics guard")

    if name.endswith("_smoke.json"):
        if classification != "SMOKE_SEMANTICS_RESULT":
            ERRORS.append(f"[FAIL] {name}: smoke file classification must be SMOKE_SEMANTICS_RESULT")
    elif name == "m7_extended_monte_carlo.json":
        if n is not None and n < 200 and classification == "FULL_MC_ACTUAL_RESULT":
            ERRORS.append(f"[FAIL] {name}: n={n} cannot be FULL_MC_ACTUAL_RESULT")
        if n is not None and n >= 200 and classification not in ("FULL_MC_ACTUAL_RESULT", "SMOKE_PASS_FULL_PENDING"):
            ERRORS.append(f"[FAIL] {name}: unexpected classification {classification!r} for full output")

    valid_stats = data.get("return_vinf_valid_only")
    if valid_stats:
        p95 = valid_stats.get("p95")
        if p95 is not None and p95 > 30.0:
            ERRORS.append(f"[FAIL] {name}: formal return_vinf summary p95={p95} > 30 km/s")
        mean = valid_stats.get("mean")
        if mean is not None and abs(mean - 79.0) < 5.0:
            ERRORS.append(f"[FAIL] {name}: formal return_vinf summary still near old invalid ~79 km/s")

    if data.get("old_invalid_return_vinf_guard") is not True:
        ERRORS.append(f"[FAIL] {name}: old_invalid_return_vinf_guard must be true")


for path in FILES:
    _check_file(path)

if ERRORS:
    for err in ERRORS:
        print(err)
    print(f"\n{len(ERRORS)} failure(s)")
    sys.exit(1)

print("OK: M7 return semantics checks passed.")
sys.exit(0)
