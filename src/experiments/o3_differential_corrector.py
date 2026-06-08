"""
o3_differential_corrector.py
==============================
O3: Custom damped Gauss-Newton differential corrector.
No scipy.optimize dependency.

Multi-parameter (2-param / 3-param), multi-start, central-difference
Jacobian, damped Gauss-Newton with line search and Tikhonov fallback.

Test problem: Moon-intercept trajectory correction (same as old O3 baseline
for fair comparison).

Residual: rocket position vs target position at fixed terminal time.
"""

import json, os, sys, time, math, csv
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import DT_REFINE, R_EARTH
from nbody import vv_step_nbody, GM_SEMR
from horizons import fetch_sem_vectors, state_at_index


# =========================
# 1. Propagation helper
# =========================

def propagate_to_target(
    r0_list: list,
    v0_list: list,
    dt_total: float,
    gm_values: list = None,
    dt_internal: float = DT_REFINE,
):
    """N-body forward propagation."""
    if gm_values is None:
        gm_values = GM_SEMR
    n_bodies = len(r0_list)
    r = [ri.copy().astype(float) for ri in r0_list]
    v = [vi.copy().astype(float) for vi in v0_list]
    t_accum = 0.0
    while t_accum < dt_total:
        step = min(dt_internal, dt_total - t_accum)
        if step <= 0:
            break
        r, v = vv_step_nbody(r, v, step, gm_values, n_bodies)
        t_accum += step
    return r, v


# =========================
# 2. Central-difference Jacobian
# =========================

def finite_difference_jacobian(F, x, eps):
    """Central-difference Jacobian.

    Parameters
    ----------
    F : callable — residual function, returns (n_res,) ndarray
    x : (n_params,) ndarray — current point
    eps : (n_params,) ndarray — per-parameter perturbation

    Returns
    -------
    J : (n_res, n_params) ndarray
    """
    n = len(x)
    fx = F(x)
    m = len(fx)
    J = np.zeros((m, n))

    for i in range(n):
        xp = x.copy()
        xm = x.copy()
        xp[i] += eps[i]
        xm[i] -= eps[i]
        fp = F(xp)
        fm = F(xm)
        J[:, i] = (fp - fm) / (2.0 * eps[i])

    return J


# =========================
# 3. Damped Gauss-Newton with line search
# =========================

LINE_SEARCH_ALPHAS = [1.0, 0.5, 0.25, 0.125, 0.0625, 0.03125]


def damped_gauss_newton(
    F,
    x0,
    eps_param,
    max_iter=12,
    tol_km=100.0,
    lam_reg=1e-8,
    verbose=True,
):
    """Damped Gauss-Newton with line search and Tikhonov fallback.

    Parameters
    ----------
    F : callable — residual(x) -> (n_res,) ndarray
    x0 : ndarray — initial parameters
    eps_param : ndarray — perturbation size per param for Jacobian
    max_iter : int
    tol_km : float — convergence target on ||F(x)||
    lam_reg : float — base Tikhonov regularisation

    Returns
    -------
    dict with:
      x_final, final_miss, improvement, iterations, converged,
      run_history, failure_reason
    """
    x = x0.copy().astype(float)
    fx0 = F(x)
    initial_miss = float(np.linalg.norm(fx0))
    fx = fx0

    # Track history
    history = []

    for it in range(max_iter):
        miss = float(np.linalg.norm(fx))
        history.append({"iter": it, "miss_km": miss, "x": x.copy()})

        if miss < tol_km:
            if verbose:
                print(f"    Converged at iter {it}, miss={miss:.2f} km")
            return _make_result(x, fx, initial_miss, it + 1, True, history, None)

        # Compute Jacobian
        eps_a = np.array([eps_param.get(k, 1e-4) for k in range(len(x))],
                         dtype=float)
        J = finite_difference_jacobian(F, x, eps_a)
        m, n = J.shape

        # Jacobian diagnostics
        try:
            U, s, Vt = np.linalg.svd(J, full_matrices=False)
            cond_j = float(s[0] / max(s[-1], 1e-30))
            rank_j = int(np.sum(s > 1e-10 * max(s[0], 1e-30)))
        except Exception:
            cond_j = float("inf")
            rank_j = 0

        # Gauss-Newton step with optional Tikhonov
        JtJ = J.T @ J
        JtF = J.T @ (-fx)
        lam = lam_reg * max(1.0, float(np.linalg.norm(JtJ)))

        try:
            A = JtJ + lam * np.eye(n)
            delta = np.linalg.solve(A, JtF)
        except np.linalg.LinAlgError:
            # Fallback: pseudo-inverse
            delta = np.linalg.lstsq(J, -fx, rcond=None)[0]

        step_norm = float(np.linalg.norm(delta))

        # Line search
        accepted = False
        alpha_used = 0.0
        for alpha in LINE_SEARCH_ALPHAS:
            xtry = x + alpha * delta
            ftry = F(xtry)
            if np.linalg.norm(ftry) < miss:
                x = xtry
                fx = ftry
                accepted = True
                alpha_used = alpha
                break

        if not accepted:
            # Try with larger regularization
            lam_big = lam * 100
            try:
                A = JtJ + lam_big * np.eye(n)
                delta2 = np.linalg.solve(A, JtF)
                for alpha in LINE_SEARCH_ALPHAS:
                    xtry = x + alpha * delta2
                    ftry = F(xtry)
                    if np.linalg.norm(ftry) < miss:
                        x = xtry
                        fx = ftry
                        accepted = True
                        alpha_used = alpha
                        break
            except Exception:
                pass

        if not accepted:
            reason = "line_search_failed"
            if verbose:
                print(f"    Line search failed at iter {it}")
            return _make_result(x, fx, initial_miss, it + 1, False,
                              history, reason)

        # Clamp parameters to bounds
        x = np.clip(x, _get_bounds(len(x))[0], _get_bounds(len(x))[1])

    # Max iterations
    final_miss = float(np.linalg.norm(fx))
    converged = final_miss < tol_km
    reason = None if converged else "max_iter_reached"
    return _make_result(x, fx, initial_miss, max_iter, converged,
                       history, reason)


def _make_result(x, fx, initial_miss, iterations, converged, history, reason):
    final_miss = float(np.linalg.norm(fx))
    return {
        "x_final": x.tolist(),
        "final_miss_km": final_miss,
        "initial_miss_km": initial_miss,
        "improvement_factor": initial_miss / max(final_miss, 1e-10),
        "iterations": iterations,
        "converged": converged,
        "failure_reason": reason,
        "run_history": history,
    }


def _get_bounds(n_params):
    """Parameter bounds for clipping."""
    if n_params == 2:
        return (np.array([-0.5, 0.5]), np.array([0.5, 1.5]))
    elif n_params == 3:
        return (np.array([-0.5, 0.5, -20.0]),
                np.array([0.5, 1.5, 20.0]))
    return (np.array([-1.0]), np.array([1.0]))


# =========================
# 4. Problem-specific residual
# =========================

def make_residual_function(body_data, t0_mjd, dt_s, target_body="Earth"):
    """Build residual function for Moon-intercept problem (2D, 4-body).

    Same setup as old O3 baseline for fair comparison:
    - Rocket departs near Earth heading toward Moon
    - Terminal time is fixed
    - Residual = rocket position - target position

    Parameters
    ----------
    body_data : dict — ephemeris
    t0_mjd : float — initial epoch
    dt_s : float — propagation time (seconds)
    target_body : str — "Earth" or "Moon"

    Returns
    -------
    F : callable — residual(x) -> (2,) ndarray
    r0_base : list — fixed initial states [Sun, Earth, Moon]
    v0_base : list — fixed initial velocities
    target_pos : ndarray — target position at terminal time
    """

    # Initial states
    r_sun3, v_sun3 = state_at_index(body_data, "Sun", 0)
    r_earth3, v_earth3 = state_at_index(body_data, "Earth", 0)
    r_moon3, v_moon3 = state_at_index(body_data, "Moon", 0)
    r_sun, v_sun = r_sun3[:2].copy(), v_sun3[:2].copy()
    r_earth, v_earth = r_earth3[:2].copy(), v_earth3[:2].copy()
    r_moon, v_moon = r_moon3[:2].copy(), v_moon3[:2].copy()

    # Propagate Sun, Earth, Moon to terminal time to get target
    r_ephem, v_ephem = propagate_to_target(
        [r_sun, r_earth, r_moon], [v_sun, v_earth, v_moon],
        dt_s, GM_SEMR,
    )
    if target_body == "Moon":
        target_idx = 2
    else:
        target_idx = 1  # Earth
    target_pos = r_ephem[target_idx].copy()

    # Baseline rocket: near Earth, heading roughly toward Moon
    v_moon_dir = v_moon / (np.linalg.norm(v_moon) + 1e-15)
    r_rocket = r_earth + 8000.0 * v_moon_dir
    v_rocket_earth_rel = 0.5 * v_moon_dir
    v_rocket = v_earth + v_rocket_earth_rel

    r0_base = [r_sun, r_earth, r_moon, r_rocket]
    v0_base = [v_sun, v_earth, v_moon, v_rocket]

    # Baseline departure params
    v_inf_vec_base = v_rocket_earth_rel  # Earth-relative
    speed0 = float(np.linalg.norm(v_inf_vec_base))
    dir0 = v_inf_vec_base / speed0

    def F(params):
        """Residual: rocket - target at fixed terminal time.

        params = [angle_rad, v_inf_scale]  (2-param)
        or
        params = [angle_rad, v_inf_scale, tof_shift_days]  (3-param)
        """
        angle = params[0]
        v_inf_scale = params[1]
        # Rotate direction
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        dir_rot = np.array([
            dir0[0] * cos_a - dir0[1] * sin_a,
            dir0[0] * sin_a + dir0[1] * cos_a,
        ])
        v_inf_vec = speed0 * v_inf_scale * dir_rot
        v_rocket_dep = v_earth + v_inf_vec

        # Apply TOF shift if 3-param
        dt_actual = dt_s
        if len(params) >= 3:
            tof_shift_s = params[2] * 86400.0
            dt_actual = max(60.0, dt_s + tof_shift_s)

        # Propagate rocket + Sun/Earth/Moon
        r4 = [ri.copy() for ri in r0_base[:3]] + [r_rocket.copy()]
        v4 = [vi.copy() for vi in v0_base[:3]] + [v_rocket_dep.copy()]
        r_fin, v_fin = propagate_to_target(r4, v4, dt_actual, GM_SEMR)
        rocket_pos = r_fin[3]

        return rocket_pos - target_pos

    # Compute baseline initial miss
    fx0 = F(np.array([0.0, 1.0]))
    initial_miss = float(np.linalg.norm(fx0))

    return F, r0_base, v0_base, target_pos, initial_miss


# =========================
# 5. Seeds and multi-start search
# =========================

SEEDS_2D = [
    [0.0, 1.0],
    [math.radians(-5), 1.0],
    [math.radians(5), 1.0],
    [0.0, 0.95],
    [0.0, 1.05],
    [math.radians(-5), 0.95],
    [math.radians(5), 1.05],
    [math.radians(-10), 1.0],
    [math.radians(10), 1.0],
]

TOF_SHIFTS = [-5, 0, 5]  # days, for 3-param seeds


def multi_start_search(F, seeds_2d, tof_shifts, eps_param_2d, eps_param_3d,
                       max_iter=12, tol_km=100.0):
    """Run damped Gauss-Newton from multiple starting points.

    Returns best result (lowest final miss).
    """
    all_results = []

    # 2-param runs
    for seed in seeds_2d:
        x0 = np.array(seed, dtype=float)
        r = damped_gauss_newton(
            F, x0, eps_param_2d, max_iter=max_iter, tol_km=tol_km, verbose=False,
        )
        r["n_params"] = 2
        r["x0"] = seed
        all_results.append(r)

    # 3-param runs (combine seed + tof_shift)
    for seed in seeds_2d:
        for tshift in tof_shifts:
            x0 = np.array([seed[0], seed[1], float(tshift)], dtype=float)
            r = damped_gauss_newton(
                F, x0, eps_param_3d, max_iter=max_iter, tol_km=tol_km, verbose=False,
            )
            r["n_params"] = 3
            r["x0"] = seed + [tshift]
            all_results.append(r)

    # Sort by final miss
    all_results.sort(key=lambda r: r["final_miss_km"])

    return all_results


# =========================
# 6. Main
# =========================

def main():
    print("=" * 66)
    print("O3: Custom Damped Gauss-Newton Differential Corrector")
    print("=" * 66)

    # ---- Load ephemeris ----
    print("\n[Step 1] Loading ephemeris...")
    body_data = fetch_sem_vectors(use_cache=True)
    t0_mjd = 61041.5
    dt_test = 0.25 * 86400.0  # 6 hours (same as old baseline)

    # ---- Build residual ----
    print(f"[Step 2] Building residual (dt={dt_test:.0f}s, target=Moon)...")
    F, r0_base, v0_base, target_pos, initial_miss = make_residual_function(
        body_data, t0_mjd, dt_test, target_body="Moon",
    )
    print(f"  Initial miss (baseline, x=[0,1]): {initial_miss:.2f} km")
    print(f"  Target pos: ({target_pos[0]:.1f}, {target_pos[1]:.1f}) km")

    # ---- Epsilon configuration ----
    eps_param_2d = {0: 1e-4, 1: 1e-4}
    eps_param_3d = {0: 1e-4, 1: 1e-4, 2: 1e-2}

    # ---- Audit old baseline first ----
    print("\n[Step 3] Auditing old baseline (x=[0,1], 1-step)...")
    fx_old = F(np.array([0.0, 1.0]))
    print(f"  Old baseline miss: {np.linalg.norm(fx_old):.2f} km")
    audit = {
        "current_method": "1-param Newton-Raphson (legacy shooting_corrector.py)",
        "parameters": ["departure_angle_rad"],
        "initial_miss_km": 2893046.5872,
        "final_miss_km": 581335.781772,
        "improvement_factor": 4.98,
        "converged": False,
        "failure_reason": "max_iter_reached (single parameter cannot control 2D position)",
        "main_limitation": "single-parameter correction; line search insufficient",
    }

    # ---- Multi-start search ----
    print(f"\n[Step 4] Multi-start search ({len(SEEDS_2D)} 2D seeds"
          f" x {len(TOF_SHIFTS)} tof = {len(SEEDS_2D) + len(SEEDS_2D)*len(TOF_SHIFTS)} runs)...")
    t0 = time.time()
    all_results = multi_start_search(
        F, SEEDS_2D, TOF_SHIFTS, eps_param_2d, eps_param_3d,
        max_iter=12, tol_km=100.0,
    )
    elapsed = time.time() - t0

    best = all_results[0]
    n_converged = sum(1 for r in all_results if r["converged"])
    n_useful = sum(1 for r in all_results
                   if r["improvement_factor"] >= 10)

    print(f"\n  Total time: {elapsed:.1f}s")
    print(f"  Runs: {len(all_results)}")
    print(f"  Converged (miss < 100 km): {n_converged}")
    print(f"  Useful (improvement >= 10x): {n_useful}")
    print(f"\n  Best result:")
    print(f"    n_params={best['n_params']}, x0={best['x0']}")
    print(f"    Initial miss: {best['initial_miss_km']:.2f} km")
    print(f"    Final miss:   {best['final_miss_km']:.4f} km")
    print(f"    Improvement:  {best['improvement_factor']:.2f}x")
    print(f"    Iterations:   {best['iterations']}")
    print(f"    Converged:    {best['converged']}")
    print(f"    x_final:      {best['x_final']}")
    print(f"    Reason:       {best['failure_reason']}")

    # Determine status
    if best["converged"]:
        status = "done"
    elif best["improvement_factor"] >= 10:
        status = "done-with-caveat"
    else:
        status = "exploratory"

    # Unpack best params
    bf = best["x_final"]
    best_angle_rad = bf[0]
    best_angle_deg = math.degrees(best_angle_rad)
    best_v_inf_scale = bf[1]
    best_tof_shift = bf[2] if len(bf) >= 3 else 0.0

    # ---- Generate convergence CSV ----
    csv_rows = []
    for i, r in enumerate(all_results):
        for h in r["run_history"]:
            csv_rows.append({
                "run_id": i,
                "iter": h["iter"],
                "miss_km": round(h["miss_km"], 4),
                "angle_rad": round(float(r["x_final"][0]), 6),
                "v_inf_scale": round(float(r["x_final"][1]), 6),
                "n_params": r["n_params"],
                "status": "converged" if r["converged"] else (
                    "useful" if r["improvement_factor"] >= 10 else "weak"),
            })

    # ---- Save ----
    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    summary = {
        "method": "custom damped Gauss-Newton differential corrector",
        "uses_scipy_optimize": False,
        "target_type": "fixed_terminal_time",
        "target_mjd": float(t0_mjd + dt_test / 86400.0),
        "residual_definition": "rocket - target position at fixed terminal time",
        "parameterization": ["departure_angle_rad", "v_inf_scale"],
        "optional_parameterization": ["tof_shift_days"],
        "baseline_legacy": {
            "method": "1-param Newton-Raphson (shooting_corrector.py)",
            "initial_miss_km": 2893046.5872,
            "final_miss_km": 581335.781772,
            "improvement_factor": 4.98,
        },
        "best_result": {
            "initial_miss_km": round(best["initial_miss_km"], 4),
            "final_miss_km": round(best["final_miss_km"], 4),
            "improvement_factor": round(best["improvement_factor"], 2),
            "iterations": best["iterations"],
            "converged": best["converged"],
            "useful": best["improvement_factor"] >= 10,
            "status": status,
            "n_params": best["n_params"],
            "x_final": [round(v, 6) for v in bf],
            "x0": best["x0"],
            "failure_reason": best["failure_reason"],
        },
        "o3_current_audit": audit,
        "seeds": {
            "2d": SEEDS_2D,
            "tof_shifts_days": TOF_SHIFTS,
        },
        "runs": [
            {
                "run_id": i,
                "n_params": r["n_params"],
                "x0": r["x0"],
                "final_miss_km": round(r["final_miss_km"], 4),
                "improvement_factor": round(r["improvement_factor"], 2),
                "converged": r["converged"],
                "iterations": r["iterations"],
            }
            for i, r in enumerate(all_results)
        ],
    }

    json_path = out_dir / "o3_shooting_corrector.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n[O3] JSON saved to {json_path}")

    csv_path = out_dir / "o3_shooting_convergence.csv"
    if csv_rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=csv_rows[0].keys())
            w.writeheader()
            w.writerows(csv_rows)
        print(f"[O3] CSV saved to {csv_path}")

    # ---- Convergence plot ----
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(9, 6))

        n_plot = min(len(all_results), 10)
        for i in range(n_plot):
            r = all_results[i]
            hist = r["run_history"]
            if hist:
                    iters = [h["iter"] for h in hist]
                    misses = [h["miss_km"] for h in hist]
                    label = f"Run {i}: {r.get('n_params', 2)}p m={r['final_miss_km']:.0f}km"
                    ax.semilogy(iters, misses, "-o", markersize=3, linewidth=1, label=label)

        ax.axhline(100, c="green", ls="--", alpha=0.5, label="Convergence threshold (100 km)")
        if best["final_miss_km"] > 0:
            ax.axhline(best["final_miss_km"], c="red", ls=":",
                       label=f"Best final miss ({best['final_miss_km']:.0f} km)")

        ax.set_xlabel("Iteration")
        ax.set_ylabel("Miss distance (km)")
        ax.set_title("O3: Damped Gauss-Newton Convergence")
        ax.legend(fontsize=7, loc="upper right")
        ax.grid(True, alpha=0.3)

        plot_path = out_dir / "o3_shooting_convergence.png"
        fig.savefig(plot_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        print(f"[O3] Plot saved to {plot_path}")

    except Exception as e:
        print(f"[O3] Plot error: {e}")

    # ---- Summary ----
    print(f"\n{'=' * 66}")
    print(f"O3: {status}")
    print(f"  Old (1-param):  initial={audit['initial_miss_km']:.0f} km, "
          f"final={audit['final_miss_km']:.0f} km, 4.98x")
    print(f"  New (multi-p):  initial={best['initial_miss_km']:.0f} km, "
          f"final={best['final_miss_km']:.4f} km, "
          f"{best['improvement_factor']:.2f}x")
    print(f"  Best params: angle={best_angle_deg:.4f} deg, "
          f"v_scale={best_v_inf_scale:.4f}, "
          f"tof_shift={best_tof_shift:.1f} days")
    print(f"  n_params={best['n_params']}, runs={len(all_results)}, "
          f"converged={n_converged}, useful={n_useful}")
    print(f"  {best['failure_reason'] or 'converged'}")
    print("=" * 66)


if __name__ == "__main__":
    main()
