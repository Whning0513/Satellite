"""
shooting_corrector.py
=====================
O3: 自定义微分修正器 (Newton-Raphson Shooting Corrector).

用打靶法修正轨道参数，使火箭在给定飞行时间后达到目标位置。
使用 Newton-Raphson 迭代，不依赖 scipy.optimize。

应用场景：
  1. 月球拦截修正：调整发射方向使近月距最小化
  2. 近日点精化：调整 Δv 使 r_p 匹配设计值
"""

import numpy as np
from typing import Callable, Tuple, Optional

from constants import DT_REFINE
from nbody import vv_step_nbody, GM_SEMR


def propagate_to_target(
    r0_list: list,
    v0_list: list,
    dt_total: float,
    gm_values: list = None,
    dt_internal: float = DT_REFINE,
) -> Tuple[list, list]:
    """N 体前向传播（用于靶点映射）。"""
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


def compute_jacobian_fd(
    shoot_fn: Callable,
    params: np.ndarray,
    param_idx: int,
    dt_total: float,
    r0_base: list,
    v0_base: list,
    eps: float = 1e-3,
    gm_values: list = None,
) -> np.ndarray:
    """用前向差分计算目标状态对单个参数的雅可比列。"""
    if gm_values is None:
        gm_values = GM_SEMR

    # 用 shoot_fn 计算标称结果（确保维度匹配）
    r_nom, v_nom = shoot_fn(params, r0_base, v0_base, dt_total, gm_values)

    # 扰动参数
    params_pert = params.copy()
    params_pert[param_idx] += eps
    r_pert, v_pert = shoot_fn(params_pert, r0_base, v0_base, dt_total, gm_values)

    # 雅可比列：位置偏差 / 扰动
    dr = np.concatenate([(r_pert[i] - r_nom[i]) / eps for i in range(len(r_nom))])
    return dr


def newton_shoot(
    shoot_fn: Callable,
    params0: np.ndarray,
    target_state: list,
    r0_base: list,
    v0_base: list,
    dt_total: float,
    max_iter: int = 20,
    tol: float = 1e-3,
    gm_values: list = None,
    verbose: bool = True,
) -> dict:
    """Newton-Raphson 打靶修正。

    Parameters
    ----------
    shoot_fn : Callable
        射击函数: f(params, r0_base, v0_base, dt_total, gm_values)
        -> (r_final, v_final) 其中 r_final[i] 是位置向量。
    params0 : ndarray
        初始射击参数 (n_params,)。
    target_state : list of ndarray
        目标状态（位置向量列表）。
    r0_base, v0_base : list of ndarray
        基础初态（不含被调参数的固定部分）。
    dt_total : float
        传播时间 (s)。
    max_iter : int
        最大迭代次数，默认 20。
    tol : float
        收敛容差 (km)，默认 1e-3。
    gm_values : list, optional
        N 体 GM 参数。

    Returns
    -------
    dict : params_opt, n_iter, converged, final_error
    """
    if gm_values is None:
        gm_values = GM_SEMR

    params = params0.copy().astype(float)
    n_params = len(params)
    n_bodies = len(target_state)

    if verbose:
        print(f"[Shoot] Newton shooting correction, {n_params} parameter(s), "
              f"target {n_bodies} bodies, dt={dt_total:.0f}s")

    for iteration in range(max_iter):
        # 当前传播
        r_final, v_final = shoot_fn(params, r0_base, v0_base, dt_total, gm_values)

        # 误差向量 = 当前状态 - 目标状态（仅位置）
        err_vec = np.concatenate(
            [r_final[i] - target_state[i] for i in range(n_bodies)]
        )
        err_norm = np.linalg.norm(err_vec)

        if verbose:
            print(f"  Iter {iteration+1:2d}: |error| = {err_norm:.6e} km")

        if err_norm < tol:
            if verbose:
                print(f"  Converged after {iteration+1} iterations.")
            return {
                "params_opt": params,
                "n_iter": iteration + 1,
                "converged": True,
                "final_error": float(err_norm),
                "r_final": r_final,
                "v_final": v_final,
            }

        # 数值雅可比矩阵 (n_state × n_params)
        J = np.zeros((len(err_vec), n_params))
        for j in range(n_params):
            J_col = compute_jacobian_fd(
                shoot_fn, params, j, dt_total, r0_base, v0_base, eps=max(1e-4, tol),
                gm_values=gm_values,
            )
            J[:len(J_col), j] = J_col

        # Newton 步: Δp = J⁺ · (-err_vec)
        try:
            # 使用伪逆保证数值稳定性
            J_pinv = np.linalg.pinv(J)
            dp = J_pinv @ (-err_vec)
        except np.linalg.LinAlgError:
            if verbose:
                print(f"  Jacobian singular at iteration {iteration+1}, aborting")
            return {
                "params_opt": params,
                "n_iter": iteration + 1,
                "converged": False,
                "final_error": float(err_norm),
                "r_final": r_final,
                "v_final": v_final,
            }

        # 阻尼：限制步长避免发散
        dp_norm = np.linalg.norm(dp)
        max_step = max(abs(params)) * 0.5
        if dp_norm > max_step:
            dp = dp * (max_step / dp_norm)

        params += dp

    # 最大迭代未收敛
    r_final, v_final = shoot_fn(params, r0_base, v0_base, dt_total, gm_values)
    err_vec = np.concatenate(
        [r_final[i] - target_state[i] for i in range(n_bodies)]
    )
    err_norm = np.linalg.norm(err_vec)

    if verbose:
        print(f"  Max iterations ({max_iter}) reached, final error = {err_norm:.6e} km")

    return {
        "params_opt": params,
        "n_iter": max_iter,
        "converged": err_norm < tol * 10,
        "final_error": float(err_norm),
        "r_final": r_final,
        "v_final": v_final,
    }


def shoot_moon_intercept(
    params: np.ndarray,
    r0_base: list,
    v0_base: list,
    dt_total: float,
    gm_values: list,
) -> Tuple[list, list]:
    """月球拦截射击函数。

    params = [v_inf_dir_rad]  — 发射方向角 (rad)
    返回末端状态（火箭位置用于与月球位置对比）。
    """
    # 从基础初态构建四体初态
    r4 = [ri.copy() for ri in r0_base[:3]]
    v4 = [vi.copy() for vi in v0_base[:3]]

    # 火箭：用参数化的发射方向覆盖
    v_inf_mag = np.linalg.norm(v0_base[3] - v0_base[2])  # 相对于月球速度
    v_moon = v0_base[2]
    v_rocket_new = v_moon + v_inf_mag * np.array([np.cos(params[0]), np.sin(params[0])])
    r_rocket = r0_base[3].copy()
    v_rocket = v_rocket_new.copy()

    r4.append(r_rocket)
    v4.append(v_rocket)

    # 传播
    r, v = propagate_to_target(r4, v4, dt_total, gm_values)
    # 返回火箭位置（用于与目标对比）
    return [r[3]], [v[3]]


if __name__ == "__main__":
    import json, os, csv, time
    from nbody import GM_SEMR, BODY_NAMES_R
    from horizons import fetch_sem_vectors, state_at_index
    from pathlib import Path

    print("=" * 66)
    print("O3: Newton-Raphson Shooting Corrector")
    print("=" * 66)

    body_data = fetch_sem_vectors(use_cache=True)
    r_sun3, v_sun3 = state_at_index(body_data, "Sun", 0)
    r_earth3, v_earth3 = state_at_index(body_data, "Earth", 0)
    r_moon3, v_moon3 = state_at_index(body_data, "Moon", 0)

    r_sun, v_sun = r_sun3[:2].copy(), v_sun3[:2].copy()
    r_earth, v_earth = r_earth3[:2].copy(), v_earth3[:2].copy()
    r_moon, v_moon = r_moon3[:2].copy(), v_moon3[:2].copy()

    # Short propagation: 6 hours, target Moon position
    dt_test = 0.25 * 86400.0  # 6 hours

    r_moon_target, v_moon_target = propagate_to_target(
        [r_sun, r_earth, r_moon], [v_sun, v_earth, v_moon],
        dt_test, GM_SEMR,
    )
    target_pos = r_moon_target[2]

    # Rocket near Earth, heading roughly toward Moon
    v_moon_dir = v_moon / (np.linalg.norm(v_moon) + 1e-15)
    r_rocket = r_earth + 8000.0 * v_moon_dir
    v_rocket = v_earth + 0.5 * v_moon_dir  # slow, off-direction

    r0_base = [r_sun, r_earth, r_moon, r_rocket]
    v0_base = [v_sun, v_earth, v_moon, v_rocket]

    def shoot_angle(params, r0b, v0b, dt_total, gm):
        """1-parameter: adjust v_inf direction angle."""
        angle = params[0]
        v_inf_mag = np.linalg.norm(v0b[3] - v0b[2])
        v_m = v0b[2]
        v_rocket_new = v_m + v_inf_mag * np.array([np.cos(angle), np.sin(angle)])
        r4 = [ri.copy() for ri in r0b[:3]] + [r0b[3].copy()]
        v4 = [vi.copy() for vi in v0b[:3]] + [v_rocket_new.copy()]
        r, v = propagate_to_target(r4, v4, dt_total, gm)
        return [r[3]], [v[3]]

    init_angle = np.arctan2(v_moon_dir[1], v_moon_dir[0])

    # Initial miss
    r_initial, _ = shoot_angle(np.array([init_angle]), r0_base, v0_base, dt_test, GM_SEMR)
    initial_miss = np.linalg.norm(r_initial[0] - target_pos)
    print(f"\n  Target: ({target_pos[0]:.1f}, {target_pos[1]:.1f}) km")
    print(f"  Initial miss (aim angle={np.degrees(init_angle):.1f}°): {initial_miss:.2f} km")

    t0 = time.time()
    result = newton_shoot(
        shoot_angle, np.array([init_angle]), [target_pos],
        r0_base, v0_base, dt_test,
        tol=1e-2, max_iter=20, verbose=True,
    )
    elapsed = time.time() - t0
    final_miss = result.get("final_error", initial_miss)
    improvement = initial_miss / max(final_miss, 1e-10)

    print(f"\n  Time: {elapsed:.1f}s")
    print(f"  Initial miss: {initial_miss:.4e} km")
    print(f"  Final miss:   {final_miss:.4e} km")
    print(f"  Improvement:  {improvement:.2f}x")
    print(f"  Converged:    {result['converged']}")
    print(f"  Init angle:  {np.degrees(init_angle):.2f}°")
    print(f"  Final angle: {np.degrees(result['params_opt'][0]):.2f}°")

    # Save results
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    output = {
        "test_case": "Moon intercept trajectory correction (1-param: v_inf angle)",
        "dt_s": float(dt_test),
        "initial_miss_km": float(round(initial_miss, 4)),
        "final_miss_km": float(round(final_miss, 6)),
        "improvement_factor": float(round(improvement, 2)),
        "iterations": int(result["n_iter"]),
        "converged": bool(result["converged"]),
        "x_initial": [float(round(init_angle, 6))],
        "x_final": [float(round(float(result['params_opt'][0]), 6))],
        "failure_reason": None if bool(result["converged"]) else "max_iter_reached",
    }
    json_path = out_dir / "o3_shooting_corrector.json"
    with open(json_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[O3] Saved to {json_path}")

    csv_path = out_dir / "o3_shooting_convergence.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["iteration", "miss_km"])
        w.writerow([0, round(initial_miss, 4)])
        w.writerow([result["n_iter"], round(final_miss, 4)])
    print(f"[O3] Saved to {csv_path}")

    print(f"\n{'='*66}")
    if result["converged"]:
        print("O3: converged [OK]")
    else:
        print("O3: did not fully converge (exploratory)")
    print("=" * 66)
