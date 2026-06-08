"""
o3_differential_corrector.py
==============================
O3: Custom damped Gauss-Newton differential corrector.
No scipy.optimize dependency.

Multi-parameter (2-param / 3-param), multi-start, central-difference
Jacobian, damped Gauss-Newton with line search and Tikhonov fallback.

Residual: rocket - body(Moon) position at fixed terminal time.
This is a position-shooting corrector — it does not constrain velocity.
"""

import json, os, sys, time, math, csv
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import DT_REFINE
from nbody import vv_step_nbody, GM_SEMR
from horizons import fetch_sem_vectors, state_at_index


def propagate(r0_list, v0_list, dt_total, gm_values=None, dt_internal=DT_REFINE):
    if gm_values is None:
        gm_values = GM_SEMR
    nb = len(r0_list)
    r = [ri.copy().astype(float) for ri in r0_list]
    v = [vi.copy().astype(float) for vi in v0_list]
    t_accum = 0.0
    while t_accum < dt_total:
        step = min(dt_internal, dt_total - t_accum)
        if step <= 0:
            break
        r, v = vv_step_nbody(r, v, step, gm_values, nb)
        t_accum += step
    return r, v


def fd_jacobian(F, x, eps):
    n = len(x); fx = F(x); m = len(fx)
    J = np.zeros((m, n))
    for i in range(n):
        xp = x.copy(); xm = x.copy()
        xp[i] += eps[i]; xm[i] -= eps[i]
        J[:, i] = (F(xp) - F(xm)) / (2.0 * eps[i])
    return J


LINE_ALPHAS = [1.0, 0.5, 0.25, 0.125, 0.0625, 0.03125]


def damped_gn(F, x0, eps_d, max_iter=10, tol_km=100.0, lam_reg=1e-8, verbose=True):
    x = x0.copy().astype(float)
    fx = F(x); init_miss = float(np.linalg.norm(fx))
    hist = []
    for it in range(max_iter):
        miss = float(np.linalg.norm(fx))
        hist.append({"iter": it, "miss_km": miss, "x": x.copy()})
        if miss < tol_km:
            if verbose:
                print(f"    Converged at iter {it}, miss={miss:.2f} km")
            return _res(x, fx, init_miss, it + 1, True, hist, None)
        eps_a = np.array([eps_d.get(k, 1e-4) for k in range(len(x))], dtype=float)
        J = fd_jacobian(F, x, eps_a)
        JtJ = J.T @ J; JtF = J.T @ (-fx)
        lam = lam_reg * max(1.0, float(np.linalg.norm(JtJ)))
        try:
            delta = np.linalg.solve(JtJ + lam * np.eye(len(x)), JtF)
        except np.linalg.LinAlgError:
            delta = np.linalg.lstsq(J, -fx, rcond=None)[0]
        accepted = False
        for alpha in LINE_ALPHAS:
            xtry = x + alpha * delta; ftry = F(xtry)
            if np.linalg.norm(ftry) < miss:
                x = xtry; fx = ftry; accepted = True; break
        if not accepted:
            try:
                delta2 = np.linalg.solve(JtJ + lam * 100 * np.eye(len(x)), JtF)
                for alpha in LINE_ALPHAS:
                    xtry = x + alpha * delta2; ftry = F(xtry)
                    if np.linalg.norm(ftry) < miss:
                        x = xtry; fx = ftry; accepted = True; break
            except Exception:
                pass
        if not accepted:
            return _res(x, fx, init_miss, it + 1, False, hist, "line_search_failed")
        bn = _bnd(len(x))
        x = np.clip(x, bn[0], bn[1])
        fx = F(x)
    fm = float(np.linalg.norm(fx))
    return _res(x, fx, init_miss, max_iter, fm < tol_km, hist,
               None if fm < tol_km else "max_iter")


def _res(x, fx, init_miss, iters, conv, hist, reason):
    fm = float(np.linalg.norm(fx))
    return {"x_final": x.tolist(), "final_miss_km": fm,
            "initial_miss_km": init_miss,
            "improvement_factor": init_miss / max(fm, 1e-10),
            "iterations": iters, "converged": conv,
            "failure_reason": reason, "run_history": hist}


def _bnd(n_params):
    if n_params == 2:
        return (np.array([-0.5, 0.5]), np.array([0.5, 1.5]))
    elif n_params == 3:
        return (np.array([-0.5, 0.5, -20.0]), np.array([0.5, 1.5, 20.0]))
    return (np.array([-1.0]), np.array([1.0]))


def make_residual(body_data, dt_s, target_body="Moon"):
    """Return (F, init_miss, get_vel_diag). F recomputes target per eval."""
    r3 = {}; v3 = {}
    for name in ["Sun", "Earth", "Moon"]:
        r3d, v3d = state_at_index(body_data, name, 0)
        r3[name], v3[name] = r3d[:2].copy(), v3d[:2].copy()
    target_idx = 2 if target_body == "Moon" else 1
    v_md = v3["Moon"] / (np.linalg.norm(v3["Moon"]) + 1e-15)
    r_rocket = r3["Earth"] + 8000.0 * v_md
    speed0 = 0.5; dir0 = v_md.copy()
    r0_base = [r3["Sun"], r3["Earth"], r3["Moon"], r_rocket]
    v0_base = [v3["Sun"], v3["Earth"], v3["Moon"], v3["Earth"] + 0.5 * v_md]
    _cap = {"rv": None, "tv": None}

    def F(params):
        angle = params[0]; vs = params[1]
        ca = math.cos(angle); sa = math.sin(angle)
        dr = np.array([dir0[0]*ca - dir0[1]*sa, dir0[0]*sa + dir0[1]*ca])
        v_dep = v3["Earth"] + speed0 * vs * dr
        dt_act = dt_s
        if len(params) >= 3:
            dt_act = max(60.0, dt_s + params[2] * 86400.0)
        re, ve = propagate(r0_base[:3], v0_base[:3], dt_act)
        tpos = re[target_idx].copy(); tvel = ve[target_idx].copy()
        r4 = [ri.copy() for ri in r0_base[:3]] + [r_rocket.copy()]
        v4 = [vi.copy() for vi in v0_base[:3]] + [v_dep.copy()]
        rf, vf = propagate(r4, v4, dt_act)
        _cap["rv"] = vf[3].copy(); _cap["tv"] = tvel.copy()
        return rf[3] - tpos

    init_miss = float(np.linalg.norm(F(np.array([0.0, 1.0]))))

    def get_vd(params):
        F(params)
        return _cap["rv"], _cap["tv"], float(np.linalg.norm(_cap["rv"] - _cap["tv"]))

    return F, init_miss, get_vd


SEEDS_2D = [[0.0, 1.0], [math.radians(-5), 1.0], [math.radians(5), 1.0]]
TOF_SHIFTS = [0]


def multi_start(F, eps_2d, eps_3d, max_iter=10, tol_km=100.0):
    all_r = []
    for s in SEEDS_2D:
        r = damped_gn(F, np.array(s), eps_2d, max_iter=max_iter, tol_km=tol_km, verbose=False)
        r["n_params"] = 2; r["x0"] = s; all_r.append(r)
    for s in SEEDS_2D:
        for ts in TOF_SHIFTS:
            x0 = np.array([s[0], s[1], float(ts)])
            r = damped_gn(F, x0, eps_3d, max_iter=max_iter, tol_km=tol_km, verbose=False)
            r["n_params"] = 3; r["x0"] = s + [ts]; all_r.append(r)
    all_r.sort(key=lambda r: r["final_miss_km"])
    return all_r


def main():
    print("=" * 66)
    print("O3: Custom Damped Gauss-Newton Differential Corrector")
    print("=" * 66)
    body_data = fetch_sem_vectors(use_cache=True)
    dt_test = 0.75 * 86400.0

    print(f"\n[1] Building residual (dt={dt_test:.0f}s, target=Moon)...")
    F, init_miss, get_vd = make_residual(body_data, dt_test, target_body="Moon")
    print(f"  Initial miss (x=[0,1]): {init_miss:.2f} km")

    eps_2d = {0: 1e-4, 1: 1e-4}
    eps_3d = {0: 1e-4, 1: 1e-4, 2: 1e-2}

    audit = {"method": "1-param NR (legacy)", "params": ["angle"],
             "initial_miss_km": 2893046.5872, "final_miss_km": 581335.781772,
             "improvement": 4.98, "converged": False,
             "reason": "single param cannot control 2D"}

    n2 = len(SEEDS_2D); n3 = len(SEEDS_2D) * len(TOF_SHIFTS)
    print(f"\n[2] Multi-start ({n2} 2D + {n3} 3D = {n2+n3} runs)...")
    t0 = time.time()
    all_r = multi_start(F, eps_2d, eps_3d)
    elapsed = time.time() - t0
    best = all_r[0]; bf = best["x_final"]
    n_cv = sum(1 for r in all_r if r["converged"])
    n_us = sum(1 for r in all_r if r["improvement_factor"] >= 10)
    st = "done" if best["converged"] else ("done-with-caveat" if best["improvement_factor"] >= 10 else "exploratory")

    print(f"\n  Time: {elapsed:.0f}s | Runs: {len(all_r)} | Converged: {n_cv} | Useful: {n_us}")
    print(f"  Best: n={best['n_params']}, init={best['initial_miss_km']:.0f} -> "
          f"final={best['final_miss_km']:.4f} km, {best['improvement_factor']:.2f}x")

    rv, tv, rel_v = get_vd(bf)
    fx_chk = F(bf); chk_miss = float(np.linalg.norm(fx_chk))
    chk_diff = abs(chk_miss - best["final_miss_km"])
    nb = best["n_params"]
    ba = {"angle_at_bound": (abs(bf[0]) >= 0.5 - 1e-6) if nb >= 1 else None,
          "vscale_at_bound": (bf[1] >= 1.5 - 1e-6 or bf[1] <= 0.5 + 1e-6) if nb >= 2 else None,
          "tof_at_bound": (abs(bf[2]) >= 20.0 - 1e-6) if nb >= 3 else None,
          "tof_bound_days": 20.0 if nb >= 3 else None}

    print(f"\n[Audit] Velocity rel={rel_v:.1f} km/s, reasonable={rel_v < 100}")
    print(f"[Audit] Rerun miss={chk_miss:.4f} km, diff={chk_diff:.2e}")
    print(f"[Audit] Bounds: {ba}")

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    csv_rows = []
    for i, r in enumerate(all_r):
        for h in r.get("run_history", []):
            csv_rows.append({"run_id": i, "iter": h["iter"],
                             "miss_km": round(h["miss_km"], 4),
                             "n_params": r["n_params"],
                             "s": "conv" if r["converged"] else ("useful" if r["improvement_factor"]>=10 else "weak")})

    summary = {"method": "custom damped Gauss-Newton", "uses_scipy_optimize": False,
               "target_type": "fixed_terminal_time",
               "target_mjd": float(61041.5 + dt_test/86400.0),
               "residual_definition": "rocket - Moon position at fixed terminal time",
               "parametrization": ["departure_angle_rad", "v_inf_scale"],
               "optional_parameterization": ["tof_shift_days"],
               "baseline_legacy": audit,
               "best_result": {
                   "initial_miss_km": round(best["initial_miss_km"], 4),
                   "final_miss_km": round(best["final_miss_km"], 4),
                   "improvement_factor": round(best["improvement_factor"], 2),
                   "iterations": best["iterations"], "converged": best["converged"],
                   "useful": best["improvement_factor"] >= 10, "status": st,
                   "n_params": best["n_params"], "x_final": [round(v, 6) for v in bf],
                   "x0": best["x0"], "failure_reason": best["failure_reason"],
                   "velocity_diagnostics": {
                       "rocket_vel_kms": [float(round(rv[0], 4)), float(round(rv[1], 4))],
                       "target_vel_kms": [float(round(tv[0], 4)), float(round(tv[1], 4))],
                       "relative_vel_kms": float(round(rel_v, 4)),
                       "relative_vel_reasonable": bool(rel_v < 100.0)},
                   "independent_check": {
                       "rerun_final_miss_km": float(round(chk_miss, 6)),
                       "matches_recorded_best": bool(chk_diff < 1e-3),
                       "diff_km": float(round(chk_diff, 10))},
                   "parameter_bound_audit": ba},
               "target_audit": {
                   "target_body": "Moon",
                   "recomputed_per_eval": True,
                   "target_not_from_rocket_state": True,
                   "tof_shift_also_shifts_target": True},
               "o3_audit": audit,
               "seeds": {"2d": SEEDS_2D, "tof_shifts": TOF_SHIFTS},
               "runs": [{"run_id": i, "n_params": r["n_params"], "x0": r["x0"],
                         "final_miss_km": round(r["final_miss_km"], 4),
                         "improvement": round(r["improvement_factor"], 2),
                         "converged": r["converged"]}
                        for i, r in enumerate(all_r)]}

    jp = out_dir / "o3_shooting_corrector.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n[O3] JSON: {jp}")

    if csv_rows:
        cp = out_dir / "o3_shooting_convergence.csv"
        with open(cp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=csv_rows[0].keys())
            w.writeheader(); w.writerows(csv_rows)
        print(f"[O3] CSV: {cp}")

    try:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(9, 6))
        for i, r in enumerate(all_r[:10]):
            hh = r.get("run_history", [])
            if hh:
                ax.semilogy([h["iter"] for h in hh], [h["miss_km"] for h in hh],
                           "-o", ms=3, lw=1,
                           label=f"Run {i}: {r['n_params']}p {r['final_miss_km']:.0f}km")
        ax.axhline(100, c="green", ls="--", alpha=0.5, label="100 km threshold")
        ax.axhline(best["final_miss_km"], c="red", ls=":",
                   label=f"Best {best['final_miss_km']:.2f} km")
        ax.set_xlabel("Iteration"); ax.set_ylabel("Miss (km)"); ax.set_yscale("log")
        ax.set_title("O3: Damped Gauss-Newton Convergence")
        ax.legend(fontsize=7); ax.grid(True, alpha=0.3)
        pp = out_dir / "o3_shooting_convergence.png"
        fig.savefig(pp, dpi=120, bbox_inches="tight"); plt.close()
        print(f"[O3] Plot: {pp}")
    except Exception as e:
        print(f"[O3] Plot error: {e}")

    print(f"\n{'='*66}")
    print(f"O3: {st}")
    print(f"  Old: {audit['final_miss_km']:.0f} km, 4.98x")
    print(f"  New: {best['initial_miss_km']:.0f} -> {best['final_miss_km']:.4f} km, "
          f"{best['improvement_factor']:.2f}x")
    print(f"  Best: angle={math.degrees(bf[0]):.2f} deg, vscale={bf[1]:.4f}, "
          f"tof={bf[2] if nb>=3 else 0:.1f} d")
    print(f"  scipy.optimize used: {summary['uses_scipy_optimize']}")
    print(f"  independent_check.matches: {summary['best_result']['independent_check']['matches_recorded_best']}")
    print("="*66)


if __name__ == "__main__":
    main()
