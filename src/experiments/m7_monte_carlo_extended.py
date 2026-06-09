"""
m7_monte_carlo_extended.py
===========================
Extends M7 Monte Carlo from 20 to 200 samples for better statistical power.
Does NOT replace main M7 result.
"""

import json, os, sys, time
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import AU_KM, R_MOON
from trajectory import solve_trajectory, DesignParams
from horizons import fetch_sem_vectors


def run_mc(n_samples, seed=42, t0_base=61066.0, sigma_t0=1.0,
           sigma_rm=500.0, sigma_rp=0.005):
    body_data = fetch_sem_vectors(use_cache=True)
    rng = np.random.default_rng(seed)
    results = []
    for i in range(n_samples):
        t0 = t0_base + rng.normal(0, sigma_t0)
        rm = R_MOON + 500 + rng.normal(0, sigma_rm)
        rp = 0.3 * AU_KM + rng.normal(0, sigma_rp * AU_KM)
        params = DesignParams(t0_mjd=t0, r_m=rm, side="trailing", r_p=rp)
        try:
            traj = solve_trajectory(params, body_data, verbose=False)
            results.append({
                "rp_AU": traj.r_p_achieved_km / AU_KM,
                "v_launch_kms": traj.v_launch,
                "v_reentry_kms": traj.v_reentry,
                "success": traj.success,
            })
        except Exception:
            results.append({"rp_AU": 0, "v_launch_kms": 0,
                            "v_reentry_kms": 0, "success": False})
    return results


def main():
    print("=" * 66)
    print("M7: Extended Monte Carlo")
    print("=" * 66)

    t0 = time.time()
    for n in [100, 200]:
        print(f"\n--- MC: {n} samples ---")
        results = run_mc(n_samples=n)
        elapsed = time.time() - t0
        rp = np.array([r["rp_AU"] for r in results if r["success"]])
        vl = np.array([r["v_launch_kms"] for r in results if r["success"]])
        vr = np.array([r["v_reentry_kms"] for r in results if r["success"]])
        n_ok = len(rp)

        out = {
            "n_samples": n, "n_success": n_ok, "seed": 42, "elapsed_s": round(elapsed, 1),
            "r_p_AU": {"mean": round(float(rp.mean()), 6), "std": round(float(rp.std()), 6),
                       "p5": round(float(np.percentile(rp, 5)), 6),
                       "p50": round(float(np.percentile(rp, 50)), 6),
                       "p95": round(float(np.percentile(rp, 95)), 6)} if n_ok > 0 else None,
            "v_launch_kms": {"mean": round(float(vl.mean()), 4), "std": round(float(vl.std()), 4)} if n_ok > 0 else None,
            "v_reentry_kms": {"mean": round(float(vr.mean()), 4), "std": round(float(vr.std()), 4)} if n_ok > 0 else None,
        }
        out_dir = _REPO / "data" / "results"
        os.makedirs(out_dir, exist_ok=True)
        jp = out_dir / "m7_monte_carlo_extended.json"
        with open(jp, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        print(f"  r_p: mean={out['r_p_AU']['mean']:.4f} std={out['r_p_AU']['std']:.4f} "
              f"[p5={out['r_p_AU']['p5']:.4f} p95={out['r_p_AU']['p95']:.4f}]")
        print(f"  v_launch: mean={out['v_launch_kms']['mean']:.2f} std={out['v_launch_kms']['std']:.4f}")
        print(f"  Time: {elapsed:.0f}s")
    print("\nDone")


if __name__ == "__main__":
    main()
