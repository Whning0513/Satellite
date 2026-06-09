"""
delta_v_budget.py
=================
Unified delta-v budget interpretation module.

Provides functions to classify velocity-like quantities and compute
standardised total-delta-v proxies.

**Core principle:**
  Natural gravitational acceleration is not fuel cost.
  Total Δv must sum control impulses / proxy braking terms,
  not integrate |gravity acceleration| dt.
"""

import json, sys, math
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def qian_style_symmetric_budget(single_leg_surface_equiv_kms: float) -> dict:
    """Qian-style symmetric total Δv.

    Departs from Earth surface to target and back using the same
    surface-equivalent impulse on each leg.

    Components
    ----------
    single_leg_surface_equiv_kms : float
        v_launch (surface to escape) for one leg.

    Returns
    -------
    dict with 'departure_leg_kms', 'return_leg_kms', 'total_kms',
    'style', 'note'.
    """
    total = single_leg_surface_equiv_kms * 2.0
    return {
        "departure_leg_kms": round(single_leg_surface_equiv_kms, 4),
        "return_leg_kms": round(single_leg_surface_equiv_kms, 4),
        "total_kms": round(total, 4),
        "style": "symmetric_patched_conic",
        "note": (
            "Qian-style symmetric budget. "
            "Both legs use the same surface-equivalent impulse. "
            "No gravity-assist, no mid-course correction."
        ),
    }


def vinf_only_budget(departure_vinf_kms: float,
                     return_vinf_kms: float) -> dict:
    """Simple v_inf-only budget (not a full ground-to-ground fuel budget).

    This omits the surface-to-escape ascent cost and the final
    landing/atmospheric braking.  Use only for interplanetary-leg
    trade-off comparisons.
    """
    total = departure_vinf_kms + return_vinf_kms
    return {
        "departure_vinf_kms": round(departure_vinf_kms, 4),
        "return_vinf_kms": round(return_vinf_kms, 4),
        "total_kms": round(total, 4),
        "style": "vinf_only",
        "note": (
            "v_inf-only budget: omits ascent from surface to parking orbit "
            "and final landing/atmospheric braking. Not comparable to "
            "full ground-to-ground total Δv."
        ),
    }


def simplified_full_proxy_budget(
    launch_cost_kms: float = 0.0,
    departure_vinf_kms: float = 0.0,
    midcourse_dv_kms: float = 0.0,
    powered_flyby_dv_kms: float = 0.0,
    reentry_braking_kms: float = 0.0,
    landing_braking_kms: float = 0.0,
    mode: str = "explicit",
) -> dict:
    """Simplified total delta-v proxy.

    Sums explicit control impulses and proxy braking terms.
    Does NOT include natural gravitational acceleration.

    Parameters
    ----------
    launch_cost_kms : launch ascent from surface to parking orbit
    departure_vinf_kms : C3-related hyperbolic excess
    midcourse_dv_kms : correction manoeuvres
    powered_flyby_dv_kms : sum of powered flyby residuals
    reentry_braking_kms : braking upon reentry interface
    landing_braking_kms : final descent / touchdown

    Returns
    -------
    dict with each component, total, and mode/note.
    """
    components = {
        "launch_cost_kms": launch_cost_kms,
        "departure_vinf_kms": departure_vinf_kms,
        "midcourse_dv_kms": midcourse_dv_kms,
        "powered_flyby_dv_kms": powered_flyby_dv_kms,
        "reentry_braking_kms": reentry_braking_kms,
        "landing_braking_kms": landing_braking_kms,
    }
    total = sum(components.values())
    return {
        "components": components,
        "total_kms": round(total, 4),
        "mode": mode,
        "note": (
            "Simplified full-proxy total Δv. "
            "All components are control impulses or proxy braking terms. "
            "Natural gravitational acceleration is excluded."
        ),
    }


def classify_velocity_quantity(name: str, value: float,
                               context: dict = None) -> dict:
    """Classify a speed-like quantity.

    Returns a dict with 'name', 'value', 'class', 'note'.
    Classes:
      heliocentric_speed       — orbital speed relative to Sun
      body_relative_vinf       — hyperbolic excess relative to a planet/moon
      maneuver_delta_v         — a single control impulse
      powered_flyby_residual   — Δv added at a flyby
      total_delta_v_budget     — sum of multiple impulses (fuel budget proxy)
      unknown                  — cannot classify
    """
    if context is None:
        context = {}
    known = {
        "earth_orbital_speed": ("heliocentric_speed",
                                "Earth orbital speed (~29.8 km/s)"),
        "moon_orbital_speed": ("heliocentric_speed",
                               "Moon orbital speed (~30 km/s helio)"),
        "venus_orbital_speed": ("heliocentric_speed",
                                "Venus orbital speed (~35 km/s)"),
        "departure_vinf": ("body_relative_vinf",
                           "Earth-relative hyperbolic excess at departure"),
        "return_vinf": ("body_relative_vinf",
                        "Earth-relative hyperbolic excess at return"),
        "v_rel_earth": ("body_relative_vinf",
                        "Rocket-Earth heliocentric vector difference "
                        "at return (NOT braking Δv)"),
        "v_reentry": ("body_relative_vinf",
                      "Reentry interface speed = "
                      "sqrt(v_rel² + V_esc²)"),
        "delta_v_norm": ("maneuver_delta_v",
                         "Corrector manoeuvre magnitude"),
        "dv_moon_powered": ("powered_flyby_residual",
                            "Powered Moon flyby correction"),
        "dv_venus_powered": ("powered_flyby_residual",
                             "Powered Venus flyby correction"),
        "dv_launch": ("maneuver_delta_v",
                      "Launch / escape impulse proxy"),
        "dv_total_m6": ("total_delta_v_budget",
                        "M6 window score dv_total = "
                        "v_launch + v_reentry (high proxy)"),
        "dv_total_o4plus": ("total_delta_v_budget",
                            "O4+ simplified MGA budget"),
        "symmetric_patched_conic": ("total_delta_v_budget",
                                    "Qian-style symmetric patched conic"),
    }
    cls, note = known.get(name, ("unknown", "No classification rule"))
    return {"name": name, "value": round(value, 4),
            "class": cls, "note": note}


# =========================
# Self-test
# =========================

def _self_test():
    print("=" * 66)
    print("delta_v_budget.py — self-test")
    print("=" * 66)

    # 1. Qian 33.4
    qian = qian_style_symmetric_budget(16.8363)
    print(f"\nQian (rp=0.2 AU): total={qian['total_kms']:.2f} km/s  "
          f"(expect 33.67)")

    # 2. M1 29.41 (our design rp=0.3)
    m1 = qian_style_symmetric_budget(14.7036)
    print(f"M1 (rp=0.3 AU):    total={m1['total_kms']:.2f} km/s  "
          f"(expect 29.41)")

    # 3. M5 Lambert 30.88 (vinf only)
    m5 = vinf_only_budget(10.66, 26.24)
    print(f"M5 Lambert (vinf): total={m5['total_kms']:.2f} km/s  "
          f"(expect 36.90; note: 30.88 used v_inf-based calc, "
          f"here using explicit dep+ret v_inf={10.66+26.24:.2f})")

    # 4. O4+ 43.56
    o4p = simplified_full_proxy_budget(
        departure_vinf_kms=10.66,
        powered_flyby_dv_kms=3.80 + 17.45,
        reentry_braking_kms=max(0, 26.65 - 15.0),
    )
    print(f"O4+: total={o4p['total_kms']:.2f} km/s  "
          f"(expect ~43.56)")

    # 5. M6 91.88
    m6 = simplified_full_proxy_budget(
        launch_cost_kms=14.70,
        reentry_braking_kms=78.68,
    )
    print(f"M6 (launch+reentry proxy): total={m6['total_kms']:.2f} km/s  "
          f"(91.88 style)")

    # 6. Classification
    tests = [
        ("earth_orbital_speed", 29.80),
        ("departure_vinf", 10.66),
        ("return_vinf", 26.24),
        ("v_rel_earth", 77.88),
        ("v_reentry", 78.68),
        ("delta_v_norm", 1.22),
        ("dv_moon_powered", 3.80),
        ("dv_total_m6", 91.88),
        ("symmetric_patched_conic", 29.41),
    ]
    print("\nClassification:")
    for name, val in tests:
        c = classify_velocity_quantity(name, val)
        print(f"  {c['name']:30s} {c['value']:8.2f} -> {c['class']:25s}")

    # Save
    json_path = _REPO / "data" / "results" / "delta_v_budget_unified.json"
    out = {
        "qian_symmetric": qian,
        "m1_symmetric": m1,
        "m5_vinf_only": m5,
        "o4plus_full": o4p,
        "m6_full": m6,
        "classifications": [
            classify_velocity_quantity(n, v) for n, v in tests
        ],
        "note": (
            "Natural gravitational acceleration is not fuel cost. "
            "Total Δv must sum control impulses or proxy braking terms, "
            "not integrate |gravity acceleration| dt."
        ),
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved unified budget to {json_path}")
    print("=" * 66)


if __name__ == "__main__":
    _self_test()
