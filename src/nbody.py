"""
nbody.py
========
N体 Velocity-Verlet 数值积分器。

两种使用模式：
1. M2 基准测试：无量纲二体圆轨道 (μ=4π²)，验证一年内位置误差 < 10⁻⁴。
2. N 体传播：Sun-Earth-Moon-Rocket 四体系统，用于真实轨道计算。

参考系：J2000 黄道平面（二维投影）。
单位体系：km-s 或无量纲（由调用方指定）。

参考文献：
[1] 钱学森. 星际航行概论. 中国宇航出版社, 2008. §5-§6.
[2] Hairer, E., Lubich, C., Wanner, G. Geometric Numerical Integration, 2nd ed., Ch. 1.
"""

import numpy as np
import warnings
from typing import Optional, Union, Callable

from constants import (
    GM_SUN, GM_EARTH, GM_MOON, GM_EARTH_MOON,
    DT_MAIN, DT_REFINE, CHECK_INTERVAL, ENERGY_TOL,
)

# =========================
# 1. 无量纲二体基准 (M2)
# =========================

# 标准引力参数：μ = 4π² 使周期 = 1
MU_2BODY = 4.0 * np.pi ** 2


def accel_2body(r: np.ndarray, mu: float = MU_2BODY) -> np.ndarray:
    """二体中心引力加速度。

    a(r) = -μ · r / |r|³

    Parameters
    ----------
    r : (2,) ndarray
        位置向量（无量纲）。
    mu : float
        引力参数，默认 4π²。

    Returns
    -------
    (2,) ndarray
        加速度向量。
    """
    norm_r = np.linalg.norm(r)
    return -mu * r / norm_r ** 3


def energy_2body(r: np.ndarray, v: np.ndarray, mu: float = MU_2BODY) -> float:
    """无量纲二体系统总能量。

    E = ½|v|² - μ/|r|
    """
    return 0.5 * np.dot(v, v) - mu / np.linalg.norm(r)


def angular_momentum_2body(r: np.ndarray, v: np.ndarray) -> float:
    """无量纲二体系统角动量（标量，二维）。

    L = x·vy - y·vx
    """
    return r[0] * v[1] - r[1] * v[0]


def exact_circle_orbit(t: np.ndarray) -> np.ndarray:
    """圆轨道精确解 (r₀=1, v₀=2π)。

    x(t) = cos(2π·t)
    y(t) = sin(2π·t)

    Parameters
    ----------
    t : (N,) ndarray
        时间数组（周期单位，t=1 为一周期）。

    Returns
    -------
    (N, 2) ndarray
        位置序列。
    """
    x = np.cos(2.0 * np.pi * t)
    y = np.sin(2.0 * np.pi * t)
    return np.column_stack((x, y))


# =========================
# 2. VV 积分器核心
# =========================

def vv_step(r: np.ndarray, v: np.ndarray, dt: float,
            accel_fn: Callable) -> tuple:
    """单步 Velocity-Verlet 积分。

    Parameters
    ----------
    r : ndarray
        当前位置向量。
    v : ndarray
        当前速度向量。
    dt : float
        步长。
    accel_fn : Callable[[ndarray], ndarray]
        加速度函数 a(r)，接受位置向量返回加速度向量。

    Returns
    -------
    tuple (r_new, v_new)
    """
    a0 = accel_fn(r)
    r_new = r + dt * v + 0.5 * dt * dt * a0
    a1 = accel_fn(r_new)
    v_new = v + 0.5 * dt * (a0 + a1)
    return r_new, v_new


def vv_integrate(r0: np.ndarray, v0: np.ndarray, dt: float, n_steps: int,
                 accel_fn: Callable,
                 callback: Optional[Callable] = None,
                 store_every: int = 1) -> dict:
    """Velocity-Verlet 多步积分。

    Parameters
    ----------
    r0, v0 : ndarray
        初态位置和速度。
    dt : float
        积分步长。
    n_steps : int
        总步数。
    accel_fn : Callable
        加速度函数。
    callback : Callable, optional
        每步回调 callback(step, r, v, accel_fn)。
    store_every : int
        每多少步保存一次轨迹，默认每步保存。

    Returns
    -------
    dict with keys: t, r, v, n_steps
    """
    ndim = r0.shape[0]
    n_store = (n_steps // store_every) + 1

    r = r0.copy().astype(float)
    v = v0.copy().astype(float)

    r_hist = np.zeros((n_store, ndim), dtype=float)
    v_hist = np.zeros((n_store, ndim), dtype=float)
    r_hist[0] = r
    v_hist[0] = v

    idx = 1
    for step in range(n_steps):
        r, v = vv_step(r, v, dt, accel_fn)
        if (step + 1) % store_every == 0 and idx < n_store:
            r_hist[idx] = r
            v_hist[idx] = v
            idx += 1
        if callback:
            callback(step, r, v, accel_fn)

    return {
        "t": np.arange(n_store, dtype=float) * dt * store_every,
        "r": r_hist,
        "v": v_hist,
        "n_steps": n_steps,
    }


# =========================
# 3. N 体加速度函数
# =========================

def nbody_accelerations(positions, gm_values, n_bodies=3):
    """计算 N 体引力加速度。

    对每个天体 i，计算所有其他天体 j ≠ i 的引力贡献总和。

    Parameters
    ----------
    positions : list of np.ndarray
        各天体的位置向量列表，每个形状为 (ndim,)。
    gm_values : list of float
        各天体的 GM 值列表。
    n_bodies : int
        天体数量，默认 3 (Sun, Earth, Moon)。

    Returns
    -------
    list of np.ndarray
        各天体的加速度向量。
    """
    ndim = positions[0].shape[0]
    acc = [np.zeros(ndim, dtype=float) for _ in range(n_bodies)]
    for i in range(n_bodies):
        for j in range(n_bodies):
            if i == j:
                continue
            dr = positions[j] - positions[i]
            dist3 = np.linalg.norm(dr) ** 3
            acc[i] += gm_values[j] * dr / dist3
    return acc


def vv_step_nbody(positions, velocities, dt, gm_values, n_bodies=3):
    """单步 N 体 Velocity-Verlet。

    Parameters
    ----------
    positions, velocities : list of np.ndarray
    dt : float
    gm_values : list of float
    n_bodies : int

    Returns
    -------
    (new_positions, new_velocities)
    """
    a0 = nbody_accelerations(positions, gm_values, n_bodies)
    new_positions = [
        positions[i] + dt * velocities[i] + 0.5 * dt * dt * a0[i]
        for i in range(n_bodies)
    ]
    a1 = nbody_accelerations(new_positions, gm_values, n_bodies)
    new_velocities = [
        velocities[i] + 0.5 * dt * (a0[i] + a1[i])
        for i in range(n_bodies)
    ]
    return new_positions, new_velocities


def propagate_nbody(r0_list, v0_list, dt_total, gm_values,
                    n_bodies=3, dt_internal=None):
    """N 体系统传播指定时间。

    Parameters
    ----------
    r0_list, v0_list : list of np.ndarray
        初态位置和速度。
    dt_total : float
        总传播时间 (s)。
    gm_values : list of float
    n_bodies : int
    dt_internal : float, optional
        内部步长，默认 DT_REFINE (60s)。

    Returns
    -------
    (r_list, v_list)
    """
    if dt_internal is None:
        dt_internal = DT_REFINE

    r = [ri.copy().astype(float) for ri in r0_list]
    v = [vi.copy().astype(float) for vi in v0_list]

    if dt_total < 0:
        raise ValueError("dt_total must be non-negative")
    if dt_total == 0:
        return r, v

    n = int(dt_total // dt_internal)
    rem = dt_total - n * dt_internal

    for _ in range(n):
        r, v = vv_step_nbody(r, v, dt_internal, gm_values, n_bodies)

    if rem > 0:
        r, v = vv_step_nbody(r, v, rem, gm_values, n_bodies)

    return r, v


# =========================
# 4. 守恒量监控
# =========================

def compute_conserved_quantities(positions, velocities, gm_values, n_bodies=3):
    """计算 N 体系统的加权守恒量（G·E 和 G·L）。

    用于监控数值积分质量。注意：这是 GM 加权的量，不直接等于物理能量/角动量，
    但其相对漂移反映积分精度。

    Returns
    -------
    (energy_star, angmom_star)
    """
    # G*E = Σ 0.5 * GM_i * |v_i|² - Σ_{i<j} GM_i * GM_j / |r_i - r_j|
    ke_star = sum(
        0.5 * gm_values[i] * np.dot(velocities[i], velocities[i])
        for i in range(n_bodies)
    )
    pe_star = 0.0
    for i in range(n_bodies):
        for j in range(i + 1, n_bodies):
            dr = np.linalg.norm(positions[j] - positions[i])
            pe_star -= gm_values[i] * gm_values[j] / dr

    energy_star = ke_star + pe_star

    # G*L = Σ GM_i * (r_i x v_i)
    ndim = positions[0].shape[0]
    angmom_star = np.zeros(ndim if ndim == 3 else 1, dtype=float)
    if ndim == 3:
        for i in range(n_bodies):
            angmom_star += gm_values[i] * np.cross(positions[i], velocities[i])
    else:
        # 2D: 标量角动量 (x*vy - y*vx)
        for i in range(n_bodies):
            angmom_star[0] += gm_values[i] * (
                positions[i][0] * velocities[i][1]
                - positions[i][1] * velocities[i][0]
            )

    return energy_star, angmom_star


def monitor_conservation(step, r, v, accel_fn,
                         E0=None, L0=None, check_interval=CHECK_INTERVAL,
                         verbose=False):
    """积分回调函数：监控能量和角动量守恒。

    用法：
        callback = partial(monitor_conservation, E0=E0, L0=L0, verbose=True)
    """
    # 此函数设计为通过偏函数使用
    pass  # 实际通过下方的 make_monitor 工厂函数实现


def make_monitor(E0, L0, check_interval=CHECK_INTERVAL, verbose=True):
    """创建守恒量监控回调。

    Returns
    -------
    Callable[[int, ndarray, ndarray, Callable], None]
    """
    def _monitor(step, r, v, accel_fn):
        nonlocal E0, L0
        if step % check_interval != 0:
            return
        E = energy_2body(r, v)
        L = angular_momentum_2body(r, v)
        rel_dE = abs((E - E0) / E0) if E0 != 0 else 0.0
        rel_dL = abs((L - L0) / L0) if L0 != 0 else 0.0
        if verbose:
            print(f"  step {step:6d}:  rel_dE = {rel_dE:.3e}  rel_dL = {rel_dL:.3e}")
        if rel_dE > 1.0 or rel_dL > 1.0:
            warnings.warn(f"Conservation broken at step {step}: "
                          f"dE/E={rel_dE:.2e}  dL/L={rel_dL:.2e}")
    return _monitor


# =========================
# 5. 误差分析
# =========================

def compute_errors_2body(rs, vs, mu=MU_2BODY):
    """计算二体系统的位置、能量和角动量误差。

    Parameters
    ----------
    rs : (N, ndim) ndarray
        位置序列。
    vs : (N, ndim) ndarray
        速度序列。
    mu : float

    Returns
    -------
    dict: pos_err, rel_E_err, rel_L_err
    """
    rN = rs[-1]
    vN = vs[-1]
    theoretical_final = np.array([1.0, 0.0])
    pos_err = np.linalg.norm(rN - theoretical_final)

    E0 = energy_2body(rs[0], vs[0], mu)
    EN = energy_2body(rN, vN, mu)
    rel_E_err = abs(EN - E0) / abs(E0)

    L0 = angular_momentum_2body(rs[0], vs[0])
    LN = angular_momentum_2body(rN, vN)
    rel_L_err = abs(LN - L0) / abs(L0)

    return {
        "pos_err": pos_err,
        "rel_E_err": rel_E_err,
        "rel_L_err": rel_L_err,
    }


def convergence_study(h_values, T=1.0, mu=MU_2BODY):
    """对多个步长进行收敛性研究。

    Parameters
    ----------
    h_values : list of float
        步长列表。
    T : float
        总积分时间（无量纲），默认 1 周期。
    mu : float

    Returns
    -------
    list of dict
    """
    r0 = np.array([1.0, 0.0], dtype=float)
    v0 = np.array([0.0, 2.0 * np.pi], dtype=float)

    results = []
    for h in h_values:
        n_steps = int(round(T / h))
        sol = vv_integrate(
            r0, v0, h, n_steps,
            accel_fn=lambda r: accel_2body(r, mu),
        )
        errors = compute_errors_2body(sol["r"], sol["v"], mu)
        results.append({
            "h": h,
            "n_steps": n_steps,
            **errors,
        })
    return results


# =========================
# 6. N 体系统辅助函数
# =========================

# Sun-Earth-Moon 标准 GM 列表
GM_SEM = [GM_SUN, GM_EARTH, GM_MOON]
BODY_NAMES = ["Sun", "Earth", "Moon"]

# Sun-Earth-Moon-Rocket 四体 (rocket 作为 test particle, GM=0)
GM_SEMR = [GM_SUN, GM_EARTH, GM_MOON, 0.0]
BODY_NAMES_R = ["Sun", "Earth", "Moon", "Rocket"]


def init_rocket_state(r_rocket: np.ndarray, v_rocket: np.ndarray):
    """创建四体系统（含火箭）的状态列表。

    Parameters
    ----------
    r_rocket, v_rocket : ndarray
        火箭的初始位置和速度。

    Returns
    -------
    r_list, v_list: 各包含 [Sun, Earth, Moon, Rocket] 四个向量。
    """
    # 占位符：实际调用前需先设置 SEM 初态
    r_sem = [np.zeros(2), np.zeros(2), np.zeros(2)]
    v_sem = [np.zeros(2), np.zeros(2), np.zeros(2)]

    r_list = r_sem + [r_rocket.copy().astype(float)]
    v_list = v_sem + [v_rocket.copy().astype(float)]
    return r_list, v_list


# =========================
# 7. M2 回归测试
# =========================

def _run_m2_regression():
    """M2 回归测试：无量纲二体圆轨道，一年内位置误差应 < 10⁻⁴。

    使用 Velocity-Verlet 积分器以 h=1e-3 步长积分 1 周期 (T=1)，
    验证年末位置误差、能量漂移和角动量漂移。
    """
    print("=" * 66)
    print("M2 Regression: 2D circular orbit (mu = 4*pi^2)")
    print("=" * 66)

    r0 = np.array([1.0, 0.0], dtype=float)
    v0 = np.array([0.0, 2.0 * np.pi], dtype=float)

    # 测试多个步长
    h_values = [2e-2, 1e-2, 5e-3, 2e-3, 1e-3]
    T = 1.0  # 一个周期

    print(f"\n{'h':<12} {'n_steps':<10} {'pos_err':<20} {'rel_E_err':<20} {'rel_L_err':<20}")
    print("-" * 82)

    results = convergence_study(h_values, T)

    for r in results:
        print(f"{r['h']:<12.1e} {r['n_steps']:<10} {r['pos_err']:<20.6e} "
              f"{r['rel_E_err']:<20.6e} {r['rel_L_err']:<20.6e}")

    print("-" * 82)

    # 验证 h=1e-3 的结果
    best = [r for r in results if r['h'] == 1e-3]
    if best:
        b = best[0]
        print(f"\nBest result (h=1e-3): pos_err = {b['pos_err']:.2e}")
        assert b['pos_err'] < 1e-4, (
            f"M2 regression FAILED: pos_err = {b['pos_err']:.2e} >= 1e-4"
        )
        print("M2 regression PASSED [OK]")
    else:
        print("WARNING: h=1e-3 result not found in convergence study")

    return results


# =========================
# 主程序
# =========================

if __name__ == "__main__":
    _run_m2_regression()
