"""
m5_lunar_budget_recompute.py
============================
Recomputes the M5 lunar-assisted candidate total Δv proxy using the
same budget function as the DSM no-lunar search.
"""

import json, os, sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

V_RET_MAX = 15.0


def main():
    print("=" * 66)
    print("M5 lunar budget recompute (same proxy as DSM no-lunar)")
    print("=" * 66)

    # M5 nominal values from regression output
    lunar = {
        "t0_mjd": 61066.0,
        "dep_vinf_kms": 10.1237,   # v_inf_earth from M5
        "ret_vinf_kms": 77.8814,   # v_rel_earth (S6)
        "v_reentry_kms": 78.6798,  # sqrt(v_rel^2 + V_esc^2)
        "swingby_dv_kms": 0.414,   # Moon swingby Δv
        "perihelion_AU": 0.2843,
    }

    # Same proxy as DSM: launch_proxy = dep_vinf
    launch_proxy = lunar["dep_vinf_kms"]

    # Lunar residual: swingby is gravity-assist (free), no powered residual
    lunar_residual = 0.0  # pure gravity assist, no fuel cost

    # Return braking (same formula: max(0, ret_vinf - 15))
    ret_brake = max(0, lunar["ret_vinf_kms"] - V_RET_MAX)
    # This is large (~62.9 km/s) because v_rel_earth is huge

    total = launch_proxy + lunar_residual + ret_brake

    out = {
        "task": "M5 lunar budget recompute (same proxy as DSM no-lunar)",
        "params": lunar,
        "budget": {
            "departure_vinf_kms": round(lunar["dep_vinf_kms"], 4),
            "launch_proxy_kms": round(launch_proxy, 4),
            "lunar_residual_kms": round(lunar_residual, 4),
            "return_vinf_kms": round(lunar["ret_vinf_kms"], 4),
            "return_braking_proxy_kms": round(ret_brake, 4),
            "total_dv_proxy_kms": round(total, 4),
        },
        "note": (
            "Gravity-assist swingby (0.414 km/s) is free. "
            "Total dv proxy = launch_proxy + return_braking_proxy. "
            "Return braking = max(0, return_vinf - 15 km/s). "
            "Same formula as DSM no-lunar search."
        ),
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    jp = out_dir / "m5_lunar_budget_recomputed.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(f"\n  dep_vinf:     {lunar['dep_vinf_kms']:.3f} km/s")
    print(f"  launch_proxy: {launch_proxy:.3f} km/s")
    print(f"  lunar_residual: {lunar_residual} km/s (free)")
    print(f"  return_vinf:  {lunar['ret_vinf_kms']:.3f} km/s")
    print(f"  return_brake: {ret_brake:.3f} km/s")
    print(f"  total_dv:     {total:.3f} km/s")
    print(f"\nSaved: {jp}")
    print("=" * 66)


if __name__ == "__main__":
    main()
