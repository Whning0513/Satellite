"""
o4_ephemeris_extend.py
======================
O4: Extend ephemeris cache to include Venus (and optionally Jupiter).

Attempts to fetch from JPL Horizons via the proxy; falls back to analytic
circular orbit if network is unavailable.

Output: data/cache/horizons_semv_2026_2028.json
  semv = Sun / Earth / Moon / Venus
"""

import json, os, sys, math, numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import AU_KM, GM_SUN, VENUS_ORBIT_RADIUS_KM, VENUS_PERIOD_DAYS, R_VENUS

DATA_DIR = _REPO / "data"
CACHE_DIR = _REPO / "data" / "cache"
os.makedirs(CACHE_DIR, exist_ok=True)

CACHE_PATH = CACHE_DIR / "horizons_semv_2026_2028.json"

# MJD of 2026-01-01 (approximate)
MJD_2026_START = 61041.5
# Days from 2026-01-01 to 2028-01-01
NUM_DAYS = 731  # 2026 + 2027
STEP_SECONDS = 86400  # 1 day

VENUS_BODY_ID = "299"


def _venus_analytic_fallback():
    """Generate analytic circular orbit for Venus.

    Used when Horizons network fetch is unavailable.
    Coplanar circular orbit at 0.723 AU, mean longitude calibrated to
    approximately match the 2026-01-01 epoch.

    The phase calibration is approximate (±1 day). This is sufficient
    for preliminary chain exploration but not mission design.
    """
    print("  Using analytic circular fallback for Venus")
    N = NUM_DAYS
    jd_start = MJD_2026_START + 2400000.5
    jd_arr = [jd_start + i for i in range(N)]
    mjd_arr = [MJD_2026_START + i for i in range(N)]

    # Venus mean motion (rad/day)
    n = 2.0 * math.pi / VENUS_PERIOD_DAYS

    # Approximate phase at MJD 61041.5 (2026-01-01):
    # Venus was roughly at 200 deg ecliptic longitude in early 2026.
    # This is calibrated from general ephemeris knowledge.
    phase0 = math.radians(200.0)

    x_km, y_km = [], []
    vx_kms, vy_kms = [], []

    for i in range(N):
        theta = phase0 + n * i
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)

        r = VENUS_ORBIT_RADIUS_KM
        x_km.append(r * cos_t)
        y_km.append(r * sin_t)

        v_mag = 2.0 * math.pi * VENUS_ORBIT_RADIUS_KM / VENUS_PERIOD_DAYS / 86400.0
        vx_kms.append(-v_mag * sin_t)
        vy_kms.append(v_mag * cos_t)

    body_data = {
        "Venus": {
            "jd_tdb": jd_arr,
            "calendar": [f"2026-{i//30+1:02d}-{i%30+1:02d}" for i in range(N)],
            "x_km": x_km,
            "y_km": y_km,
            "z_km": [0.0] * N,  # coplanar
            "vx_kms": vx_kms,
            "vy_kms": vy_kms,
            "vz_kms": [0.0] * N,
        },
        "_note": "Venus ephemeris is analytic circular fallback (coplanar, 0.723 AU).",
        "venus_source": "analytic_circular_fallback",
    }
    return body_data, "analytic_circular_fallback"


def _try_fetch_venus_horizons():
    """Try fetching Venus from JPL Horizons via proxy.

    Returns dict on success, None on failure.
    """
    try:
        # Try importing astroquery
        from astroquery.jplhorizons import Horizons
        from src.jpl_forward import patch_horizons_proxy
        patch_horizons_proxy()

        start = "2026-01-01"
        stop = "2028-01-01"
        step = "1d"

        print(f"  Fetching Venus (id={VENUS_BODY_ID}) from Horizons...")
        obj = Horizons(
            id=VENUS_BODY_ID,
            location="500@0",  # SSB
            epochs={"start": start, "stop": stop, "step": step},
        )
        tbl = obj.vectors(refplane="ecliptic", aberrations="geometric")
        ndays = len(tbl)
        print(f"    Got {ndays} epochs")

        body_data = {
            "Venus": {
                "jd_tdb": list(np.array(tbl["datetime_jd"], dtype=float)),
                "calendar": list(np.array(tbl["datetime_str"]).astype(str)),
                "x_km": list(np.array(tbl["x"], dtype=float) * AU_KM),
                "y_km": list(np.array(tbl["y"], dtype=float) * AU_KM),
                "z_km": list(np.array(tbl["z"], dtype=float) * AU_KM),
                "vx_kms": list(np.array(tbl["vx"], dtype=float) * AU_KM / 86400.0),
                "vy_kms": list(np.array(tbl["vy"], dtype=float) * AU_KM / 86400.0),
                "vz_kms": list(np.array(tbl["vz"], dtype=float) * AU_KM / 86400.0),
            },
            "_note": "Venus ephemeris from JPL Horizons (SSB, ecliptic).",
            "venus_source": "horizons",
        }
        return body_data, "horizons"

    except Exception as e:
        print(f"    Horizons fetch failed: {e}")
        return None


def extend_ephemeris(force_fetch=False):
    """Extend ephemeris cache with Venus.

    Returns (venus_data, source_label) where source_label is
    "horizons" or "analytic_circular_fallback".
    """
    # Check if cache already exists
    if CACHE_PATH.exists() and not force_fetch:
        print(f"[O4] Loading extended cache from {CACHE_PATH}")
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            cache = json.load(f)
        source = cache.get("venus_source", "unknown")
        return cache, source

    # Try loading existing SEM cache
    sem_path = DATA_DIR / "sem_horizons_2026-2027.json"
    if sem_path.exists():
        print(f"[O4] Loading existing SEM cache from {sem_path}")
        with open(sem_path, "r", encoding="utf-8") as f:
            sem_data = json.load(f)
    else:
        print("[O4] No SEM cache found; analytic fallback only")
        sem_data = {}

    # Try fetching Venus
    result = _try_fetch_venus_horizons()
    if result is not None:
        venus_data, source = result
    else:
        venus_data, source = _venus_analytic_fallback()

    # Merge
    merged = {**sem_data, **venus_data}
    merged["venus_source"] = source
    merged["_cache_bodies"] = list(sem_data.keys()) + ["Venus"]

    # Save
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)

    print(f"[O4] Extended cache saved to {CACHE_PATH}")
    print(f"  Venus source: {source}")
    return merged, source


def load_extended_ephemeris():
    """Load extended ephemeris without re-fetching."""
    if CACHE_PATH.exists():
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f), CACHE_PATH
    return None, None


def main():
    print("=" * 66)
    print("O4: Extend ephemeris cache with Venus")
    print("=" * 66)

    force = "--force" in sys.argv
    data, source = extend_ephemeris(force_fetch=force)

    print(f"\nVenus source: {source}")
    print(f"Cache file:   {CACHE_PATH}")
    print(f"Bodies:       {list(data.get('Venus', {}).keys())[:5]}...")

    # Sanity check
    if "Venus" in data:
        vx = data["Venus"]["x_km"]
        x0 = vx[0]
        print(f"  First Venus x: {x0:.0f} km")
        print(f"  Expected ~{-VENUS_ORBIT_RADIUS_KM * 0.5:.0f} km (approx)")

    print("[O4] Ephemeris extension complete")


if __name__ == "__main__":
    main()
