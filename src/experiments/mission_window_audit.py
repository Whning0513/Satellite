"""
mission_window_audit.py
======================
Checks whether current formal result anchors respect the original assignment
launch window and whether the Horizons cache covers the required mission span.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
RESULTS = REPO / "data" / "results"
sys.path.insert(0, str(SRC))

from horizons import fetch_sem_vectors
from mission_constraints import (
    MISSION_LAUNCH_END_DATE,
    MISSION_LAUNCH_END_MJD,
    MISSION_LAUNCH_START_DATE,
    MISSION_LAUNCH_START_MJD,
    MISSION_MAX_TOTAL_DAYS,
    mjd_to_date_str,
)


def _load(name: str):
    path = RESULTS / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    print("=" * 66)
    print("Mission window / cache coverage audit")
    print("=" * 66)
    print(
        f"formal launch window: {MISSION_LAUNCH_START_DATE}..{MISSION_LAUNCH_END_DATE} "
        f"(MJD {MISSION_LAUNCH_START_MJD:.0f}..{MISSION_LAUNCH_END_MJD:.0f})"
    )
    print(f"formal max total flight days: {MISSION_MAX_TOTAL_DAYS:.2f}")

    body_data = fetch_sem_vectors(use_cache=True)
    mjd_min = float(body_data["Earth"]["jd_tdb"][0] - 2400000.5)
    mjd_max = float(body_data["Earth"]["jd_tdb"][-1] - 2400000.5)
    required_return_max = MISSION_LAUNCH_END_MJD + MISSION_MAX_TOTAL_DAYS
    print(f"cache coverage: MJD {mjd_min:.0f}..{mjd_max:.0f}")
    print(f"cache dates: {mjd_to_date_str(mjd_min)}..{mjd_to_date_str(mjd_max)}")
    print(f"required return coverage upper bound: MJD {required_return_max:.2f}")
    print(f"required return coverage date: {mjd_to_date_str(required_return_max)}")
    print(f"cache covers full mission horizon: {mjd_max >= required_return_max}")

    for name, key in [
        ("m5_best_lunar_candidate_verify.json", ("candidate", "t0_mjd")),
        ("m5_t61037_lunar_vs_no_lunar_deep_compare.json", ("same_t0",)),
        ("m6_legal_window_search.json", ("best_valid_candidate", "t0_mjd")),
        ("m6_complete_return_window_search.json", ("best_valid_candidate", "t0_mjd")),
        ("m7_extended_monte_carlo.json", ("reference_candidate", "t0_mjd")),
    ]:
        data = _load(name)
        if not data:
            print(f"{name}: missing")
            continue
        cur = data
        value = None
        for part in key:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
                value = cur
            else:
                value = None
                break
        print(f"{name}: anchor_t0={value} date={mjd_to_date_str(value) if isinstance(value, (int, float)) else 'N/A'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
