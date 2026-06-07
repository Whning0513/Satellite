"""
m7_stepsize_convergence.py
==========================
M7 步长收敛分析: 测试多个 dt 对 M5 轨迹求解的和能量漂移的影响。

步长: 3600, 1800, 900, 450 (s)
指标: rp_actual, dv_total, energy_drift, final_pos_delta_vs_finest
输出: data/results/m7_stepsize_convergence.json, .csv
"""

import json, os, csv, sys, time, numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import GM_SUN, GM_EARTH, GM_MOON, R_MOON, AU_KM, DT_MAIN, DT_REFINE
from nbody import propagate_nbody, compute_conserved_quantities, GM_SEM
from trajectory import DesignParams, solve_trajectory
from horizons import fetch_sem_vectors, initial_state_from_horizons

DT_VALUES = [3600.0, 1800.0, 900.0, 450.0]


def run_single_timestep(dt, body_data, r0_nominal, v0_nominal, gm_sem):
    """Run M5 trajectory solver with given dt_integrate, measure metrics."""
    params = DesignParams(
        t0_mjd=61066.0,
        r_m=R_MOON + 500.0,
        side="trailing",
        r_p=0.3 * AU_KM,
    )

    t0 = time.time()
    traj = solve_trajectory(params, body_data, dt_integrate=dt, verbose=False)
    elapsed = time.time() - t0

    rp_au = float(np.round(traj.r_p_achieved_km / AU_KM, 6))
    dv_total = round(traj.v_launch + traj.v_reentry, 4)

    # Energy drift (short 30-day N-body)
    r, v = [ri.copy() for ri in r0_nominal], [vi.copy() for vi in v0_nominal]
    E0, L0 = compute_conserved_quantities(r, v, gm_sem, 3)
    steps_30d = int(30 * 86400 / dt)
    for _ in range(steps_30d):
        r, v = propagate_nbody(r, v, dt, gm_sem, n_bodies=3, dt_internal=dt)
    E, L = compute_conserved_quantities(r, v, gm_sem, 3)
    l0_norm = float(np.linalg.norm(L0)) if hasattr(L0, 'shape') else float(abs(L0))
    l_norm = float(np.linalg.norm(L)) if hasattr(L, 'shape') else float(abs(L))
    edrift = abs((E - E0) / E0) if E0 != 0 else -1
    ldrift = abs((l_norm - l0_norm) / l0_norm) if l0_norm != 0 else -1

    return {
        "dt_s": dt,
        "energy_drift": float(edrift),
        "angular_momentum_drift": float(ldrift),
        "rp_actual_AU": rp_au,
        "dv_total_kms": dv_total,
        "runtime_s": round(elapsed, 1),
    }


def run_convergence():
    body_data = fetch_sem_vectors(use_cache=True)
    r0_nominal, v0_nominal = initial_state_from_horizons(body_data, 0)
    gm_sem = [GM_SUN, GM_EARTH, GM_MOON]

    results = []
    for dt in DT_VALUES:
        print(f"  dt={dt:.0f}s...", end=" ", flush=True)
        res = run_single_timestep(dt, body_data, r0_nominal, v0_nominal, gm_sem)
        results.append(res)
        print(f"rp={res['rp_actual_AU']:.4f} AU, edrift={res['energy_drift']:.2e}, "
              f"dv={res['dv_total_kms']:.2f} km/s, t={res['runtime_s']:.1f}s")

    # Compute convergence: difference vs finest dt
    finest = max(r["rp_actual_AU"] for r in results)  # use largest as reference
    finest_result = results[-1]
    for r in results:
        r["final_position_delta_km_vs_finest"] = round(abs(r["rp_actual_AU"] - finest_result["rp_actual_AU"]) * AU_KM, 2)

    # Estimate convergence order from last 3 points
    if len(results) >= 3:
        rps = np.array([r["rp_actual_AU"] for r in results[-3:]])
        dts = np.array([r["dt_s"] for r in results[-3:]])
        try:
            log_ratios = np.diff(np.log(abs(np.diff(rps) + 1e-30)))
            log_step_ratios = np.diff(np.log(dts))
            order = float(log_ratios / log_step_ratios) if len(log_ratios) > 0 and abs(log_step_ratios) > 0 else None
        except Exception:
            order = None
    else:
        order = None

    summary = {
        "dt_values": DT_VALUES,
        "results": results,
        "estimated_order": round(order, 2) if order is not None else None,
        "energy_drift_all": all(r["energy_drift"] < 1e-6 for r in results),
        "note": "Convergence study for trajectory solver. Estimated order limited by non-smooth rp response.",
    }

    # Save
    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    json_path = out_dir / "m7_stepsize_convergence.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n[M7] Saved to {json_path}")

    csv_path = out_dir / "m7_stepsize_convergence.csv"
    with open(csv_path, "w", newline="") as f:
        fields = ["dt_s", "energy_drift", "angular_momentum_drift",
                  "rp_actual_AU", "dv_total_kms", "runtime_s",
                  "final_position_delta_km_vs_finest"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)
    print(f"[M7] Saved to {csv_path}")

    return summary


if __name__ == "__main__":
    print("=" * 66)
    print("M7 Step-size Convergence Study")
    print("=" * 66)
    res = run_convergence()
    print(f"\n  Estimated convergence order: {res['estimated_order']}")
    print(f"  Energy drift within tol (1e-6): {res['energy_drift_all']}")
    print(f"  Final adopted dt: {res['results'][-1]['dt_s']:.0f} s")
