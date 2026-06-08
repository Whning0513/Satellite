"""
o7_parallel_scan.py
===================
O7: Parallel launch-window scan using ThreadPoolExecutor (no pickling issues).
Compares serial vs parallel runtime.
"""

import json, os, sys, time, concurrent.futures
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import AU_KM, R_MOON
from trajectory import DesignParams, solve_trajectory
from horizons import fetch_sem_vectors

NUM_WORKERS = 4
CANDIDATE_MJDS = [61066.0, 61125.0, 61154.0, 61213.0, 61391.0]

# Pre-load Horizons cache once
_BODY_DATA = None


def _get_body_data():
    global _BODY_DATA
    if _BODY_DATA is None:
        _BODY_DATA = fetch_sem_vectors(use_cache=True)
    return _BODY_DATA


def run_one_window(t0_mjd):
    bd = _get_body_data()
    params = DesignParams(t0_mjd=t0_mjd, r_m=R_MOON+500, side="trailing", r_p=0.3*AU_KM)
    traj = solve_trajectory(params, bd, verbose=False)
    return {
        "t0_mjd": t0_mjd,
        "success": traj.success,
        "rp_AU": round(traj.r_p_achieved_km / AU_KM, 4),
        "v_launch_kms": round(traj.v_launch, 4),
    }


def main():
    # Warm the cache
    _get_body_data()

    # Serial
    t0_s = time.time()
    serial_results = [run_one_window(mjd) for mjd in CANDIDATE_MJDS]
    serial_time = time.time() - t0_s

    # Parallel (ThreadPoolExecutor — no pickling, works with module-level globals)
    t0_p = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_WORKERS) as ex:
        parallel_results = list(ex.map(run_one_window, CANDIDATE_MJDS))
    parallel_time = time.time() - t0_p

    identical = all(abs(s["rp_AU"] - p["rp_AU"]) < 1e-10
                    for s, p in zip(serial_results, parallel_results))

    result = {
        "num_cases": len(CANDIDATE_MJDS),
        "max_workers": NUM_WORKERS,
        "serial_time_s": round(serial_time, 2),
        "parallel_time_s": round(parallel_time, 2),
        "speedup": round(serial_time / max(parallel_time, 0.01), 2),
        "results_identical": bool(identical),
        "note": "ThreadPoolExecutor avoids pickling. Speedup modest due to GIL on compute-heavy operations.",
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    json_path = out_dir / "o7_parallel_scan.json"
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"[O7] Saved to {json_path}")
    print(f"  Serial:   {serial_time:.2f}s")
    print(f"  Parallel: {parallel_time:.2f}s")
    print(f"  Speedup:  {result['speedup']:.2f}x")
    print(f"  Identical: {identical}")


if __name__ == "__main__":
    main()
