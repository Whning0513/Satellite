"""
event_semantics.py
==================
Trajectory event classification and safe Earth-return computation.

Provides functions to:
  1. Classify where the spacecraft is relative to Earth.
  2. Compute Earth-relative return v_inf only when near Earth.
  3. Refuse to compute return quantities at deep-space / perihelion.

Threshold: 1.5e6 km (≈ Earth SOI radius).  If the spacecraft is farther
than this from Earth, the state does NOT represent an Earth-return event.
"""

import numpy as np

# Earth SOI radius (km) — used as threshold for "near Earth"
EARTH_SOI_KM = 9.25e5
RETURN_EVENT_THRESHOLD_KM = 1.5e6  # slightly generous SOI boundary


def classify_event(r_sc_km, r_earth_km, r_sun_km=None,
                   threshold_km=RETURN_EVENT_THRESHOLD_KM):
    """Classify the spacecraft's dynamical event type.

    Parameters
    ----------
    r_sc_km : ndarray (2,) or (3,) — spacecraft heliocentric position.
    r_earth_km : ndarray — Earth heliocentric position.
    r_sun_km : ndarray or None — Sun position (for perihelion detection).
    threshold_km : float — max Earth distance to count as return event.

    Returns
    -------
    str : one of 'earth_return', 'perihelion', 'deep_space', or
          'earth_departure' (if close to Earth at early time).
    """
    dist_earth = float(np.linalg.norm(np.array(r_sc_km) - np.array(r_earth_km)))

    if dist_earth <= threshold_km:
        return "earth_return"

    if r_sun_km is not None:
        dist_sun = float(np.linalg.norm(np.array(r_sc_km) - np.array(r_sun_km)))
        earth_sun = float(np.linalg.norm(np.array(r_earth_km) - np.array(r_sun_km)))
        # Perihelion: significantly closer to Sun than Earth is
        if dist_sun < 0.5 * earth_sun:
            return "perihelion"

    return "deep_space"


def compute_earth_return_vinf(r_sc_km, v_sc_kms,
                               r_earth_km, v_earth_kms,
                               threshold_km=RETURN_EVENT_THRESHOLD_KM):
    """Compute Earth-relative return v_inf, but ONLY if near Earth.

    Parameters
    ----------
    r_sc_km, v_sc_kms : ndarray — spacecraft state (heliocentric).
    r_earth_km, v_earth_kms : ndarray — Earth state (heliocentric).
    threshold_km : float — max Earth distance for valid return.

    Returns
    -------
    dict with keys:
      valid_return_event : bool
      distance_to_earth_km : float
      event_type : str
      return_vinf_kms : float or None
      reentry_speed_kms : float or None
      reason : str or None
    """
    dist_earth = float(np.linalg.norm(r_sc_km - r_earth_km))
    event_type = classify_event(r_sc_km, r_earth_km, threshold_km=threshold_km)

    if dist_earth > threshold_km:
        return {
            "valid_return_event": False,
            "distance_to_earth_km": round(dist_earth, 1),
            "event_type": event_type,
            "return_vinf_kms": None,
            "reentry_speed_kms": None,
            "reason": (
                f"spacecraft is {dist_earth:.0f} km from Earth "
                f"(>{threshold_km:.0f} km threshold); "
                "this is not an Earth-return event"
            ),
        }

    # Spacecraft is near Earth — compute return quantities
    from constants import V_ESCAPE_EARTH
    v_rel = v_sc_kms - v_earth_kms
    ret_vinf = float(np.linalg.norm(v_rel))
    v_reentry = float(np.sqrt(V_ESCAPE_EARTH ** 2 + ret_vinf ** 2))

    return {
        "valid_return_event": True,
        "distance_to_earth_km": round(dist_earth, 1),
        "event_type": "earth_return",
        "return_vinf_kms": round(ret_vinf, 4),
        "reentry_speed_kms": round(v_reentry, 4),
        "reason": None,
    }
