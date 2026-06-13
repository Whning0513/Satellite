"""
mission_constraints.py
=====================
Shared mission-level date and validity constraints for the Qian project.

The original assignment defines:
  - launch date window: 2026-01-01 .. 2026-12-31
  - total flight time: <= 2 years

These constraints are treated here as hard numerical validity rules for
formal M5/M6/M7 results.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from constants import T_MAX_DAYS


MJD_EPOCH = datetime(1858, 11, 17)

MISSION_LAUNCH_START_DATE = "2026-01-01"
MISSION_LAUNCH_END_DATE = "2026-12-31"

# Padding before/after the formal mission interval for transfer setup and
# event-window refinement. These do not expand the allowed launch window.
EPHEMERIS_START_DATE = "2025-12-01"
EPHEMERIS_STOP_DATE = "2029-03-01"


def date_str_to_mjd(date_str: str) -> float:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return float((dt - MJD_EPOCH).days)


def mjd_to_date_str(mjd: float) -> str:
    dt = MJD_EPOCH + timedelta(days=float(mjd))
    return dt.strftime("%Y-%m-%d")


MISSION_LAUNCH_START_MJD = date_str_to_mjd(MISSION_LAUNCH_START_DATE)
MISSION_LAUNCH_END_MJD = date_str_to_mjd(MISSION_LAUNCH_END_DATE)
MISSION_MAX_TOTAL_DAYS = float(T_MAX_DAYS)


def is_launch_mjd_in_window(t0_mjd: float) -> bool:
    t0 = float(t0_mjd)
    return MISSION_LAUNCH_START_MJD <= t0 <= MISSION_LAUNCH_END_MJD


def validate_launch_mjd(t0_mjd: float, *, label: str = "launch t0") -> None:
    if is_launch_mjd_in_window(t0_mjd):
        return
    raise ValueError(
        f"{label}={float(t0_mjd):.2f} ({mjd_to_date_str(float(t0_mjd))}) is outside the "
        f"formal assignment launch window [{MISSION_LAUNCH_START_DATE}, {MISSION_LAUNCH_END_DATE}] "
        f"(MJD {MISSION_LAUNCH_START_MJD:.0f}..{MISSION_LAUNCH_END_MJD:.0f})"
    )


def is_total_flight_time_valid(total_days: float) -> bool:
    return float(total_days) <= MISSION_MAX_TOTAL_DAYS
