"""
m7_monte_carlo_extended.py
===========================
Extends M7 Monte Carlo from 20 to 200 samples for better statistical power.

The reference trajectory must stay aligned with the currently validated
M5 Earth-return candidate instead of the obsolete 61066 half-trajectory.
This script therefore uses the verified fixed-date lunar solution:
  t0 = 61037.0, side = trailing, r_m = 1837.4 km, r_p ~= 0.3 AU.
"""

import json, os, sys, time
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import AU_KM
from trajectory import solve_trajectory, DesignParams
from horizons import fetch_sem_vectors


M5_VALID_T0 = 61037.0
M5_VALID_RM_KM = 1837.4
M5_VALID_SIDE = "trailing"
M5_VALID_RP_AU = 0.3


def _summary(values):
    if len(values) == 0:
        return None
    arr = np.asarray(values, dtype=float)
    return {
        "mean": round(float(arr.mean()), 6),
        "std": round(float(arr.std()), 6),
        "p5": round(float(np.percentile(arr, 5)), 6),
        "p50": round(float(np.percentile(arr, 50)), 6),
        "p95": round(float(np.percentile(arr, 95)), 6),
    }


def run_mc(
    n_samples,
    seed=42,
    t0_base=M5_VALID_T0,
    sigma_t0=1.0,
    sigma_rm=500.0,
    sigma_rp=0.005,
):
    body_data = fetch_sem_vectors(use_cache=True)
    rng = np.random.default_rng(seed)
    results = []
    for i in range(n_samples):
        t0 = t0_base + rng.normal(0, sigma_t0)
        rm = M5_VALID_RM_KM + rng.normal(0, sigma_rm)
        rp = M5_VALID_RP_AU * AU_KM + rng.normal(0, sigma_rp * AU_KM)
        params = DesignParams(t0_mjd=t0, r_m=rm, side=M5_VALID_SIDE, r_p=rp)
        try:
            traj = solve_trajectory(params, body_data, verbose=False)
            departure_vinf = float(traj.v_inf_earth)
            return_vinf = float(traj.v_rel_earth)
            braking = max(0.0, return_vinf - 15.0)
            results.append({
                "t0_mjd": round(float(t0), 6),
                "r_m_km": round(float(rm), 3),
                "rp_AU": traj.r_p_achieved_km / AU_KM,
                "departure_vinf_kms": departure_vinf,
                "return_vinf_kms": return_vinf,
                "return_braking_proxy_kms": braking,
                "total_vinf_basis_kms": departure_vinf + braking,
                "success": traj.success,
            })
        except Exception:
            results.append({
                "t0_mjd": round(float(t0), 6),
                "r_m_km": round(float(rm), 3),
                "rp_AU": 0.0,
                "departure_vinf_kms": 0.0,
                "return_vinf_kms": 0.0,
                "return_braking_proxy_kms": 0.0,
                "total_vinf_basis_kms": 0.0,
                "success": False,
            })
    return results


def main():
    print("=" * 66)
    print("M7: Extended Monte Carlo")
    print("=" * 66)
    print(
        f"Reference candidate: t0={M5_VALID_T0:.0f}, "
        f"r_m={M5_VALID_RM_KM:.1f} km, side={M5_VALID_SIDE}, "
        f"target_rp={M5_VALID_RP_AU:.1f} AU"
    )

    t0 = time.time()
    for n in [100, 200]:
        print(f"\n--- MC: {n} samples ---")
        results = run_mc(n_samples=n)
        elapsed = time.time() - t0
        rp = np.array([r["rp_AU"] for r in results if r["success"]], dtype=float)
        dep = np.array([r["departure_vinf_kms"] for r in results if r["success"]], dtype=float)
        ret = np.array([r["return_vinf_kms"] for r in results if r["success"]], dtype=float)
        tot = np.array([r["total_vinf_basis_kms"] for r in results if r["success"]], dtype=float)
        n_ok = len(rp)

        out = {
            "task": "M7 extended Monte Carlo",
            "reference_candidate": {
                "source": "validated_M5_lunar_return",
                "t0_mjd": M5_VALID_T0,
                "r_m_km": M5_VALID_RM_KM,
                "side": M5_VALID_SIDE,
                "target_rp_AU": M5_VALID_RP_AU,
            },
            "n_samples": n,
            "n_success": n_ok,
            "seed": 42,
            "elapsed_s": round(elapsed, 1),
            "r_p_AU": _summary(rp),
            "departure_vinf_kms": _summary(dep),
            "return_vinf_kms": _summary(ret),
            "total_vinf_basis_kms": _summary(tot),
        }
        out_dir = _REPO / "data" / "results"
        os.makedirs(out_dir, exist_ok=True)
        jp = out_dir / "m7_monte_carlo_extended.json"
        with open(jp, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        print(f"  r_p: mean={out['r_p_AU']['mean']:.4f} std={out['r_p_AU']['std']:.4f} "
              f"[p5={out['r_p_AU']['p5']:.4f} p95={out['r_p_AU']['p95']:.4f}]")
        print(
            f"  dep_vinf: mean={out['departure_vinf_kms']['mean']:.2f} "
            f"std={out['departure_vinf_kms']['std']:.4f}"
        )
        print(
            f"  total_vinf_basis: mean={out['total_vinf_basis_kms']['mean']:.2f} "
            f"std={out['total_vinf_basis_kms']['std']:.4f}"
        )
        print(f"  Time: {elapsed:.0f}s")
    print("\nDone")


if __name__ == "__main__":
    main()
