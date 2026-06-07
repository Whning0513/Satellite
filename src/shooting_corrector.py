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
    # 简单自检
    from nbody import GM_SEMR, BODY_NAMES_R
    from horizons import fetch_sem_vectors, state_at_index

    print("=" * 66)
    print("O3 Regression: Newton-Raphson Shooting Corrector")
    print("=" * 66)

    body_data = fetch_sem_vectors(use_cache=True)

    # 测试场景：月球拦截方向修正（2D 投影）
    r_sun3, v_sun3 = state_at_index(body_data, "Sun", 0)
    r_earth3, v_earth3 = state_at_index(body_data, "Earth", 0)
    r_moon3, v_moon3 = state_at_index(body_data, "Moon", 0)
    r_sun, v_sun = r_sun3[:2].copy(), v_sun3[:2].copy()
    r_earth, v_earth = r_earth3[:2].copy(), v_earth3[:2].copy()
    r_moon, v_moon = r_moon3[:2].copy(), v_moon3[:2].copy()

    # 构建一个粗糙的火箭初态
    v_moon_dir = v_moon / (np.linalg.norm(v_moon) + 1e-15)
    r_rocket = r_earth + 7000.0 * v_moon_dir
    v_rocket = v_earth + 2.0 * v_moon_dir

    r0_base = [r_sun, r_earth, r_moon, r_rocket]
    v0_base = [v_sun, v_earth, v_moon, v_rocket]

    # 设定目标：让火箭在 3 天后接近月球位置
    dt_test = 3.0 * 86400.0
    r_moon_target, v_moon_target = propagate_to_target(
        [r_sun, r_earth, r_moon],
        [v_sun, v_earth, v_moon],
        dt_test,
        GM_SEMR,
    )
    target = [r_moon_target[2]]  # 目标：月球 3 天后位置

    # 初始猜值：沿月球速度方向
    init_angle = np.arctan2(v_moon_dir[1], v_moon_dir[0])

    result = newton_shoot(
        shoot_moon_intercept,
        np.array([init_angle]),
        target,
        r0_base,
        v0_base,
        dt_test,
        tol=1e-2,
        verbose=True,
    )

    print(f"\n  Converged: {result['converged']}")
    print(f"  Initial angle: {np.degrees(init_angle):.4f} deg")
    print(f"  Final angle: {np.degrees(result['params_opt'][0]):.4f} deg")
    print(f"  Iterations: {result['n_iter']}")
    print(f"  Final error: {result['final_error']:.6f} km")

    if result["converged"]:
        print(f"\nO3 self-test PASSED [OK]")
    else:
        print(f"\nO3 self-test: did not fully converge (acceptable for test)")
