"""
m5_lunar_budget_recompute.py
============================
Recomputes the M5 lunar-assisted candidate total Δv proxy using the
SAME budget function as the DSM no-lunar search.

Budget definition (both lunar and no-lunar):
  launch_proxy   = actual departure v_inf of the trajectory
  lunar residual = 0.0 (gravity-assist is free — no powered component)
  return_braking = max(0, return_vinf - 15 km/s)
  total_dv       = launch_proxy + dsm/residual + return_braking

Note: the M5 lunar trajectory has return v_rel_earth = 77.88 km/s
(≫ 15 km/s).  The return braking term dominates the lunar budget.

Output: data/results/m5_lunar_budget_recomputed.json
"""

import json, os, sys, math
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import V_ESCAPE_EARTH

V_RET_MAX = 15.0


def main():
    print("=" * 66)
    print("M5 lunar budget recompute (same proxy as DSM no-lunar)")
    print("=" * 66)

    # Use values from M5 regression output (stored, not re-run)
    dep_vinf = 10.1213           # from M5 solve_trajectory v_inf_earth
    ret_vinf = 77.8814           # v_rel_earth (actual)
    swingby_dv = 0.4138          # swingby dv_mag
    peri_au = 0.2843             # r_p_achieved

    print(f"  M5 trajectory actual values:")
    print(f"    t0_mjd:         61066.0")
    print(f"    dep_vinf:       {dep_vinf:.4f} km/s")
    print(f"    swingby dv:     {swingby_dv:.4f} km/s")
    print(f"    return_vinf:    {ret_vinf:.4f} km/s")
    print(f"    perihelion:     {peri_au:.4f} AU")
    print()

    # ── Budget (same formula as DSM no-lunar) ──
    lunar_residual = 0.0                 # gravity assist is free
    return_brake = max(0, ret_vinf - V_RET_MAX)
    total_dv = dep_vinf + lunar_residual + return_brake

    lunar_params = {
        "t0_mjd": 61066.0,
        "return_vinf_kms": round(float(ret_vinf), 4),
        "v_reentry_kms": round(float(math.sqrt(11.18**2 + ret_vinf**2)), 4),
        "swingby_delta_v_kms": round(float(swingby_dv), 4),
        "swingby_is_gravitational": True,
        "perihelion_AU": round(float(peri_au), 4),
        "dep_vinf_actual_kms": round(float(dep_vinf), 4),
    }

    out = {
        "task": "M5 lunar budget recompute (same proxy as DSM no-lunar)",
        "budget_function": "actual_departure_vinf + max(0, return_vinf - 15)",
        "params": lunar_params,
        "budget": {
            "departure_vinf_kms": round(float(dep_vinf), 4),
            "launch_proxy_kms": round(float(dep_vinf), 4),
            "lunar_residual_kms": round(float(lunar_residual), 4),
            "return_vinf_kms": round(float(ret_vinf), 4),
            "return_braking_proxy_kms": round(float(return_brake), 4),
            "total_dv_proxy_kms": round(float(total_dv), 4),
        },
        "note": (
            "Gravity-assist swingby is free (no fuel cost). "
            "Budget = actual_departure_vinf + max(0, return_vinf - 15). "
            "Same formula as DSM no-lunar search. "
            f"Actual departure v_inf = {dep_vinf:.4f} km/s "
            "(from N-body trajectory solver, NOT patched-conic ideal)."
        ),
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    jp = out_dir / "m5_lunar_budget_recomputed.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(f"  Budget components:")
    print(f"    departure_vinf:    {dep_vinf:.4f} km/s")
    print(f"    launch_proxy:      {dep_vinf:.4f} km/s  (= departure_vinf)")
    print(f"    lunar_residual:    {lunar_residual} km/s  (free gravity assist)")
    print(f"    return_vinf:       {ret_vinf:.4f} km/s")
    print(f"    return_braking:    {return_brake:.4f} km/s  (max(0, r_vinf - 15))")
    print(f"    total_dv_proxy:    {total_dv:.4f} km/s")
    print(f"\nSaved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
