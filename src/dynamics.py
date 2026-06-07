"""
dynamics.py
===========
动力学引擎：N 体加速度计算，支持多种参考系和积分模式。

提供三种加速度模式：
  barycentric      : SSB 惯性系标准 N 体引力 (∀i≠j)
  heliocentric_relative : 日心相对坐标，含 indirect term，物理上等价于
                         在 SSB 惯性系积分后转换到日心系（非事后扣押）
  numerical_basis  : 无物理简化，只做浮点运算路由

日心相对坐标动力学方程：
  对非太阳天体 i：
    a_i = -μ_⊙ · r_i/|r_i|³
        + Σ_{j≠i,⊙} μ_j · [(r_j - r_i)/|r_j - r_i|³ - r_j/|r_j|³]
  太阳固定为坐标原点 (a_⊙ ≡ 0)。

  其中第一项为日心主导引力，第二项为第三体摄动（含 indirect term）。
  该公式与 SSB 惯性系动力学完全等价——区别仅在坐标系选取，
  不改变积分结果。
"""

import numpy as np
from typing import List, Optional

# =========================
# 1. SSB 惯性系加速度
# =========================

def accel_barycentric(
    positions: List[np.ndarray],
    gm_values: List[float],
    n_bodies: int,
) -> List[np.ndarray]:
    """SSB 惯性系下的标准 N 体加速度。

    对每个天体 i：
      a_i = Σ_{j≠i} GM_j · (r_j - r_i) / |r_j - r_i|³

    Parameters
    ----------
    positions : list of ndarray
        各天体位置，每个形状 (ndim,)。
    gm_values : list of float
        各天体的 GM 值。
    n_bodies : int

    Returns
    -------
    list of ndarray : 加速度向量列表
    """
    ndim = positions[0].shape[0]
    acc = [np.zeros(ndim, dtype=float) for _ in range(n_bodies)]
    for i in range(n_bodies):
        for j in range(n_bodies):
            if i == j:
                continue
            dr = positions[j] - positions[i]
            dist3 = np.linalg.norm(dr) ** 3
            if dist3 > 0:
                acc[i] += gm_values[j] * dr / dist3
    return acc


# =========================
# 2. 日心相对坐标加速度
# =========================

def accel_heliocentric_relative(
    positions: List[np.ndarray],
    gm_values: List[float],
    n_bodies: int,
    sun_idx: int = 0,
) -> List[np.ndarray]:
    """日心相对坐标下的加速度（含 indirect term）。

    参考系原点固定在太阳，动力学方程完全等价于 SSB 惯性系方程，
    仅做坐标变换后重写。

    Parameters
    ----------
    positions : list of ndarray
        日心相对位置。positions[sun_idx] 应为 0。
    gm_values : list of float
        各天体的 GM 值，gm_values[sun_idx] = GM_Sun。
    n_bodies : int
    sun_idx : int, default 0

    Returns
    -------
    list of ndarray : 日心相对加速度列表。
        positions[sun_idx] 保持为 0。
    """
    ndim = positions[0].shape[0]
    mu_sun = gm_values[sun_idx]
    acc = [np.zeros(ndim, dtype=float) for _ in range(n_bodies)]

    # 太阳加速度置零
    acc[sun_idx] = np.zeros(ndim)

    for i in range(n_bodies):
        if i == sun_idx:
            continue

        r_i = positions[i]
        r_i_norm = np.linalg.norm(r_i)

        # 日心主导项：-μ_⊙ · r_i / |r_i|³
        if r_i_norm > 0:
            acc[i] += -mu_sun * r_i / (r_i_norm ** 3)

        # 自项修正：-μ_i · r_i / |r_i|³
        # 物理含义：太阳本身受到天体 i 的引力，在日心非惯性系中需补偿
        if r_i_norm > 0 and gm_values[i] > 0:
            acc[i] += -gm_values[i] * r_i / (r_i_norm ** 3)

        # 第三体摄动（含 indirect term）
        for j in range(n_bodies):
            if j == sun_idx or j == i:
                continue
            r_j = positions[j]
            dr = r_j - r_i
            dr_norm3 = np.linalg.norm(dr) ** 3
            r_j_norm3 = np.linalg.norm(r_j) ** 3

            # direct term
            if dr_norm3 > 0:
                acc[i] += gm_values[j] * dr / dr_norm3
            # indirect term（太阳受天体 j 的引力在日心系中的表现）
            if r_j_norm3 > 0:
                acc[i] -= gm_values[j] * r_j / r_j_norm3

    return acc


def accel_heliocentric_direct_only(
    positions: List[np.ndarray],
    gm_values: List[float],
    n_bodies: int,
    sun_idx: int = 0,
) -> List[np.ndarray]:
    """日心相对坐标下的加速度（仅 direct term，不含 indirect term）。

    与 accel_heliocentric_relative 的区别：
    缺少 indirect term (-μ_j · r_j/|r_j|³)，这在数学上不等于 SSB 积分后转换。
    用于 ablation 实验以评估 indirect term 的贡献。

    Parameters
    ----------
    positions : list of ndarray
    gm_values : list of float
    n_bodies : int
    sun_idx : int

    Returns
    -------
    list of ndarray
    """
    ndim = positions[0].shape[0]
    mu_sun = gm_values[sun_idx]
    acc = [np.zeros(ndim, dtype=float) for _ in range(n_bodies)]
    acc[sun_idx] = np.zeros(ndim)

    for i in range(n_bodies):
        if i == sun_idx:
            continue
        r_i = positions[i]
        r_i_norm = np.linalg.norm(r_i)
        if r_i_norm > 0:
            acc[i] += -mu_sun * r_i / (r_i_norm ** 3)

        for j in range(n_bodies):
            if j == sun_idx or j == i:
                continue
            dr = positions[j] - r_i
            dr_norm3 = np.linalg.norm(dr) ** 3
            if dr_norm3 > 0:
                acc[i] += gm_values[j] * dr / dr_norm3

    return acc


# =========================
# 3. 积分器路由
# =========================

def vv_step_nbody(
    positions: List[np.ndarray],
    velocities: List[np.ndarray],
    dt: float,
    gm_values: List[float],
    n_bodies: int,
    accel_mode: str = "barycentric",
    sun_idx: int = 0,
) -> tuple:
    """单步 Velocity-Verlet 积分，支持多种加速度模式。

    Parameters
    ----------
    positions, velocities : list of ndarray
    dt : float
    gm_values : list of float
    n_bodies : int
    accel_mode : str
        "barycentric", "heliocentric_relative", "heliocentric_direct_only"
    sun_idx : int

    Returns
    -------
    (new_positions, new_velocities)
    """
    if accel_mode == "barycentric":
        accel_fn = accel_barycentric
    elif accel_mode == "heliocentric_relative":
        accel_fn = lambda p, gm, n: accel_heliocentric_relative(p, gm, n, sun_idx)  # noqa: E731
    elif accel_mode == "heliocentric_direct_only":
        accel_fn = lambda p, gm, n: accel_heliocentric_direct_only(p, gm, n, sun_idx)  # noqa: E731
    else:
        raise ValueError(f"Unknown accel_mode: {accel_mode}")

    a0 = accel_fn(positions, gm_values, n_bodies)
    new_positions = [
        positions[i] + dt * velocities[i] + 0.5 * dt * dt * a0[i]
        for i in range(n_bodies)
    ]
    a1 = accel_fn(new_positions, gm_values, n_bodies)
    new_velocities = [
        velocities[i] + 0.5 * dt * (a0[i] + a1[i])
        for i in range(n_bodies)
    ]
    return new_positions, new_velocities


# =========================
# 4. 传播函数
# =========================

def propagate_nbody(
    r0_list: List[np.ndarray],
    v0_list: List[np.ndarray],
    dt_total: float,
    gm_values: List[float],
    n_bodies: int = 3,
    dt_internal: Optional[float] = None,
    accel_mode: str = "barycentric",
    sun_idx: int = 0,
) -> tuple:
    """N 体系统传播指定时间，支持多种加速度模式。

    Parameters
    ----------
    r0_list, v0_list : list of ndarray
    dt_total : float
    gm_values : list of float
    n_bodies : int
    dt_internal : float, optional
        内部步长，默认 60s (DT_REFINE)。
    accel_mode : str
    sun_idx : int

    Returns
    -------
    (r_list, v_list)
    """
    from constants import DT_REFINE
    if dt_internal is None:
        dt_internal = DT_REFINE

    if dt_total < 0:
        raise ValueError("dt_total must be non-negative")
    if dt_total == 0:
        return [ri.copy() for ri in r0_list], [vi.copy() for vi in v0_list]

    r = [ri.copy().astype(float) for ri in r0_list]
    v = [vi.copy().astype(float) for vi in v0_list]

    n = int(dt_total // dt_internal)
    rem = dt_total - n * dt_internal

    for _ in range(n):
        r, v = vv_step_nbody(r, v, dt_internal, gm_values, n_bodies, accel_mode, sun_idx)
    if rem > 0:
        r, v = vv_step_nbody(r, v, rem, gm_values, n_bodies, accel_mode, sun_idx)

    return r, v
