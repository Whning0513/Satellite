"""
o7_parallel_scan.py
===================
O7: Parallel launch-window scan using ProcessPoolExecutor for true
multi-core speedup (no GIL limitation).

Comparisons:
  1. Serial vs ProcessPool batch parallel on N top windows (M6 feasible days)
  2. Speedup vs number of workers
  3. Result consistency check

Use --repeat N to run multiple trials and report mean/min/max/std speedup.
"""

import argparse
import json
import os
import sys
import time
import concurrent.futures
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import AU_KM, R_MOON
from trajectory import DesignParams, solve_trajectory
from horizons import fetch_sem_vectors
from optimize_window import scan_launch_window

_NUM_WORKERS = min(8, os.cpu_count() or 4)
_CHUNK_SIZE = 10  # MJDs per chunk — each subprocess gets N days at once


def run_one_serial(mjd, body_data):
    """Run one trajectory in-process (for serial baseline)."""
    params = DesignParams(
        t0_mjd=mjd, r_m=R_MOON + 500.0, side="trailing", r_p=0.3 * AU_KM,
    )
    traj = solve_trajectory(params, body_data, verbose=False)
    return {
        "t0_mjd": float(mjd),
        "success": bool(traj.success),
        "rp_AU": float(round(traj.r_p_achieved_km / AU_KM, 4)),
        "v_launch_kms": float(round(traj.v_launch, 4)),
        "v_reentry_kms": float(round(traj.v_reentry, 4)),
    }


def _build_chunks(mjd_list, chunk_size=_CHUNK_SIZE):
    """Split MJD list into chunks for ProcessPool workers.

    Each chunk is: (chunk_id, [mjds...], r_m_km, side, r_p_km)
    """
    r_m_km = R_MOON + 500.0
    r_p_km = 0.3 * AU_KM
    chunks = []
    for i in range(0, len(mjd_list), chunk_size):
        chunk = mjd_list[i:i + chunk_size]
        chunks.append((i // chunk_size, chunk, r_m_km, "trailing", r_p_km))
    return chunks


def run_single_scan(test_mjds, body_data, num_workers):
    """Run one serial + parallel round, return (serial_time, parallel_time,
    serial_results, parallel_results, n_consistent)."""
    # ---- Serial baseline ----
    t0_ser = time.time()
    serial_results = [run_one_serial(mjd, body_data) for mjd in test_mjds]
    t_serial = time.time() - t0_ser
    n_ok_ser = sum(1 for r in serial_results if r["success"])

    # ---- Parallel batching ----
    chunks = _build_chunks(test_mjds, chunk_size=_CHUNK_SIZE)
    from experiments.o7_worker import run_mjd_chunk

    t0_par = time.time()
    with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as pool:
        future_map = {pool.submit(run_mjd_chunk, ch): ch[0] for ch in chunks}
        parallel_raw = []
        for f in concurrent.futures.as_completed(future_map):
            try:
                data = f.result()
                parallel_raw.append(data)
            except Exception as e:
                print(f"  Chunk {future_map[f]} FAILED: {e}")
    t_parallel = time.time() - t0_par

    parallel_by_mjd = {}
    for chunk_data in parallel_raw:
        for r in chunk_data["results"]:
            parallel_by_mjd[r["t0_mjd"]] = r
    parallel_results = [parallel_by_mjd.get(m, {}) for m in test_mjds]
    n_ok_par = sum(1 for r in parallel_results if r.get("success"))

    # ---- Consistency ----
    n_consistent = 0
    for s, p in zip(serial_results, parallel_results):
        s_rp = s.get("rp_AU", -1)
        p_rp = p.get("rp_AU", -2)
        if abs(s_rp - p_rp) < 1e-6:
            n_consistent += 1

    return t_serial, t_parallel, n_ok_ser, n_ok_par, n_consistent


def main():
    parser = argparse.ArgumentParser(description="O7 ProcessPool parallel scan")
    parser.add_argument("--repeat", type=int, default=1,
                        help="Number of repeated trials (default=1)")
    parser.add_argument("--benchmark-only", action="store_true",
                        help="Only run benchmark, skip single-scan output")
    args = parser.parse_args()

    print("=" * 66)
    print("O7: Parallel Launch-Window Scan via ProcessPoolExecutor")
    print("=" * 66)
    print(f"\nNUM_WORKERS = {_NUM_WORKERS},  CHUNK_SIZE = {_CHUNK_SIZE}")
    print(f"Workers map to {os.cpu_count()} logical CPUs")

    # ---- Phase 0: Quick M6 scan ----
    print("\n[Phase 0] Scanning 366-day window (M6 fast scan)...")
    body_data = fetch_sem_vectors(use_cache=True)
    result = scan_launch_window(
        r_p_AU=0.3, r_m_km=R_MOON + 500.0, side="trailing",
        mode="fast", verbose=False,
    )
    feasible_mjds = sorted([
        w.t0_mjd for w in result.windows if w.feasible
    ])
    print(f"  {len(feasible_mjds)} feasible days found")

    test_mjds = sorted(feasible_mjds[:min(30, len(feasible_mjds))])
    if len(feasible_mjds) > 30:
        spread = feasible_mjds[::4]
        for m in spread:
            if m not in test_mjds:
                test_mjds.append(m)
    test_mjds = sorted(set(test_mjds))
    print(f"  Using {len(test_mjds)} test days for trajectory solve")
    print(f"  MJD range: [{test_mjds[0]:.1f}, {test_mjds[-1]:.1f}]")

    # ---- Single scan (or first scan if --repeat) ----
    print(f"\n[Phase 1] Primary evaluation ({len(test_mjds)} days)...")
    t_serial, t_parallel, n_ok_ser, n_ok_par, n_consistent = run_single_scan(
        test_mjds, body_data, _NUM_WORKERS,
    )
    speedup = t_serial / max(t_parallel, 0.01)
    print(f"  Serial:   {t_serial:.2f}s ({n_ok_ser}/{len(test_mjds)} success)")
    print(f"  Parallel: {t_parallel:.2f}s ({n_ok_par}/{len(test_mjds)} success)")
    print(f"  Speedup:  {speedup:.2f}x")
    print(f"  Identical: {n_consistent}/{len(test_mjds)}")

    # ---- Save primary scan results ----
    if not args.benchmark_only:
        result_data = {
            "num_cases": len(test_mjds),
            "max_workers": _NUM_WORKERS,
            "chunk_size": _CHUNK_SIZE,
            "serial_time_s": round(t_serial, 2),
            "parallel_time_s": round(t_parallel, 2),
            "speedup": round(speedup, 2),
            "results_identical": n_consistent == len(test_mjds),
            "num_identical": n_consistent,
            "num_total": len(test_mjds),
            "serial_success_rate": f"{n_ok_ser}/{len(test_mjds)}",
            "parallel_success_rate": f"{n_ok_par}/{len(test_mjds)}",
            "test_mjd_range": [float(test_mjds[0]), float(test_mjds[-1])],
            "note": (
                "ProcessPoolExecutor batching: each subprocess loads Horizons cache "
                "once and solves a chunk of MJDs. True multi-core speedup "
                "compared to GIL-bound ThreadPool."
            ),
        }
        out_dir = _REPO / "data" / "results"
        os.makedirs(out_dir, exist_ok=True)
        json_path = out_dir / "o7_parallel_scan.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, indent=2, ensure_ascii=False)
        print(f"\n[O7] Primary result saved to {json_path}")

    # ---- Repeated benchmark (optional) ----
    if args.repeat > 1:
        print(f"\n[Benchmark] Repeating scan {args.repeat} times...")
        runs = []
        all_consistent = True
        for i in range(args.repeat):
            print(f"  Run {i+1}/{args.repeat}...")
            ts, tp, n_ok_s, n_ok_p, n_cons = run_single_scan(
                test_mjds, body_data, _NUM_WORKERS,
            )
            sp = ts / max(tp, 0.01)
            runs.append({
                "serial_time_s": round(ts, 2),
                "parallel_time_s": round(tp, 2),
                "speedup": round(sp, 2),
            })
            if n_cons != len(test_mjds):
                all_consistent = False
            print(f"    serial={ts:.1f}s parallel={tp:.1f}s speedup={sp:.2f}x "
                  f"identical={n_cons}/{len(test_mjds)}")

        speedups = [r["speedup"] for r in runs]
        benchmark_result = {
            "repeat": args.repeat,
            "num_cases": len(test_mjds),
            "max_workers": _NUM_WORKERS,
            "chunk_size": _CHUNK_SIZE,
            "runs": runs,
            "mean_speedup": round(float(np.mean(speedups)), 4),
            "min_speedup": round(float(np.min(speedups)), 4),
            "max_speedup": round(float(np.max(speedups)), 4),
            "std_speedup": round(float(np.std(speedups, ddof=1)), 4) if args.repeat > 1 else 0.0,
            "results_identical_all_runs": all_consistent,
            "note": (
                "Benchmark: each run includes serial + parallel scan. "
                "Speedup variation reflects OS scheduling and disk cache effects."
            ),
        }
        out_dir = _REPO / "data" / "results"
        os.makedirs(out_dir, exist_ok=True)
        bench_path = out_dir / "o7_parallel_benchmark.json"
        with open(bench_path, "w", encoding="utf-8") as f:
            json.dump(benchmark_result, f, indent=2, ensure_ascii=False)
        print(f"\n[Benchmark] Results saved to {bench_path}")
        print(f"  mean speedup: {benchmark_result['mean_speedup']:.2f}x")
        print(f"  min speedup:  {benchmark_result['min_speedup']:.2f}x")
        print(f"  max speedup:  {benchmark_result['max_speedup']:.2f}x")
        print(f"  std speedup:  {benchmark_result['std_speedup']:.4f}")
        print(f"  all runs identical: {all_consistent}")

    print(f"\n{'=' * 66}")
    print("[O7] Complete")


if __name__ == "__main__":
    main()
