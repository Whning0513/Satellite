"""
patched_conic.py
================
拼接圆锥曲线法（Patched Conic Method）核心函数。

基于钱学森《星际航行概论》§5-§6 的步骤一至步骤六框架。
提供从日心椭圆轨道参数计算到地面发射速度的完整函数链。

参考系：J2000 黄道平面，二维投影。
单位体系：km-s。

参考文献：
[1] 钱学森. 星际航行概论. 中国宇航出版社, 2008. §§5-6.
[2] Vallado, D. A. Fundamentals of Astrodynamics and Applications, 4th ed., §12.4.
[3] Curtis, H. D. Orbital Mechanics for Engineering Students, 3rd ed., §8.10.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from constants import (
    GM_SUN, AU_KM, R_SUN, R_EARTH_ORBIT,
    V_EARTH_ORBIT, V_ESCAPE_EARTH, T_EARTH_YEAR,
    VE_SQ, V2_SQ,
)
from units import deg_to_rad, rad_to_deg


# =========================
# 数据类型定义
# =========================

@dataclass
class OrbitalElements:
    """日心椭圆轨道根数 (heliocentric orbital elements)

    所有公式来自钱书 §5-§6。
    """
    r_p: float               # 近日距 (km)
    r_1: float               # 出发/返回点日心距 (km)，通常 = 1 AU
    K_s: float               # 太阳向心力常数 = GM_SUN (km³/s²)

    # 派生量（由 compute() 填充）
    a: float = field(init=False)       # 半长轴 (km)
    e: float = field(init=False)       # 偏心率
    p: float = field(init=False)       # 半通径 (km)
    v_1: float = field(init=False)     # 出发/返回点日心速度 (km/s)
    delta_v: float = field(init=False) # 日心速度增量 (km/s)
    v_launch: float = field(init=False) # 地面发射速度 (km/s)
    T: float = field(init=False)       # 轨道周期 (s)
    T_days: float = field(init=False)  # 轨道周期 (天)
    dt_flight: float = field(init=False)  # 飞行时间 (s)，默认取半周期
    dt_flight_days: float = field(init=False)  # 飞行时间 (天)
    v_reentry: float = field(init=False)  # 再入速度 ≈ √(v₂² + v_∞²)

    def compute(self) -> 'OrbitalElements':
        """执行全部轨道参数计算"""
        r_p, r_1, K_s = self.r_p, self.r_1, self.K_s

        # 步骤三：轨道根数 (§6.2)
        self.a = (r_1 + r_p) / 2.0
        self.e = (r_1 - r_p) / (r_1 + r_p)
        self.p = 2.0 * r_1 * r_p / (r_1 + r_p)

        # 步骤四：出发日心速度与速度增量 (§6.3)
        # v_1 = v_e * √(2r_p/(r₁+r_p))  见式(6.8)
        v_e = np.sqrt(K_s / r_1)
        self.v_1 = v_e * np.sqrt(2.0 * r_p / (r_1 + r_p))
        self.delta_v = self.v_1 - v_e  # 为负表示减速

        # 步骤五：地面发射速度 (§6.3 第一方案)
        # v_发射 = √(v₂² + |Δv|²)
        self.v_launch = np.sqrt(V2_SQ + self.delta_v ** 2)

        # 步骤六：轨道周期与飞行时间 (§5.4, §6.2)
        self.T = 2.0 * np.pi * np.sqrt(self.a ** 3 / K_s)
        self.T_days = self.T / 86400.0

        # 半周期飞行时间（从 P₁ 经近日点到 r = r₁ 的时间）
        # 在钱书的简化模型中，出发点为远日点(θ=π)，
        # 飞过近日点(θ=0)后回到 r = r₁。
        # 对于 r₁ = 远日距，第一个满足 r = r₁ 的位置就是远日点(θ=π)，
        # 从远日点回到远日点的总时间为 T（完整轨道周期）。
        # 但根据钱书数值例，半周期 T/2 对应从远日点到近日点再到达 r₁。
        # 本实现提供两种口径：T (全周期) 和 T/2 (半周期)。
        # 默认使用半周期以匹配钱书数值例。
        self.dt_flight = self.T / 2.0
        self.dt_flight_days = self.dt_flight / 86400.0

        # 再入速度
        # v_∞,返回 ≈ |Δv|（共面向返回）
        # v_再入 ≈ √(v₂² + v_∞²)
        v_inf_return = abs(self.delta_v)
        self.v_reentry = np.sqrt(V2_SQ + v_inf_return ** 2)

        return self

    def summary_dict(self) -> dict:
        """返回可读的结果摘要"""
        return {
            "r_p_AU": self.r_p / AU_KM,
            "r_1_AU": self.r_1 / AU_KM,
            "a_AU": self.a / AU_KM,
            "e": self.e,
            "p_AU": self.p / AU_KM,
            "v_1_kms": self.v_1,
            "delta_v_kms": self.delta_v,
            "v_launch_kms": self.v_launch,
            "T_days": self.T_days,
            "dt_flight_days": self.dt_flight_days,
            "v_reentry_kms": self.v_reentry,
        }

    def __repr__(self) -> str:
        s = self.summary_dict()
        lines = [
            "=== Patched Conic Elements ===",
            f"r_p  = {s['r_p_AU']:.4f} AU  ({self.r_p:.4e} km)",
            f"r_1  = {s['r_1_AU']:.4f} AU  ({self.r_1:.4e} km)",
            f"a    = {s['a_AU']:.4f} AU  ({self.a:.4e} km)",
            f"e    = {s['e']:.6f}",
            f"p    = {s['p_AU']:.4f} AU  ({self.p:.4e} km)",
            f"v_1  = {self.v_1:.4f} km/s",
            f"dv   = {self.delta_v:.4f} km/s",
            f"v_launch = {self.v_launch:.4f} km/s",
            f"T    = {self.T_days:.2f} days ({self.T_days/365.25:.4f} yr)",
            f"dt_flight = {self.dt_flight_days:.2f} days",
            f"v_reentry = {self.v_reentry:.4f} km/s",
            "==============================",
        ]
        return "\n".join(lines)


# =========================
# 核心计算函数（过程式接口）
# =========================

def compute_patched_conic(
    r_p_AU: float,
    r_1_AU: float = 1.0,
    K_s: float = GM_SUN,
) -> OrbitalElements:
    """从近日距计算完整的拼接圆锥曲线轨道参数。

    Parameters
    ----------
    r_p_AU : float
        近日距，单位 AU。
    r_1_AU : float, optional
        出发/返回点的日心距，默认 1.0 AU。
    K_s : float, optional
        太阳向心力常数，默认 GM_SUN。

    Returns
    -------
    OrbitalElements
        包含全部轨道根数和速度增量的数据类。
    """
    r_p = r_p_AU * AU_KM
    r_1 = r_1_AU * AU_KM
    elements = OrbitalElements(r_p=r_p, r_1=r_1, K_s=K_s)
    return elements.compute()


# =========================
# 相位匹配条件 (§6.3 步骤七)
# =========================

def compute_phase_matching(
    dt_flight_days: float,
    T_earth_days: float = T_EARTH_YEAR,
) -> dict:
    """计算相位匹配条件。

    火箭在飞行时间 Δt 内扫过的角度，
    与地球在相同时间内运动的角度的匹配条件，
    决定了发射窗口。

    Parameters
    ----------
    dt_flight_days : float
        飞行时间 (天)。
    T_earth_days : float, optional
        地球公转周期，默认 365.25 天。

    Returns
    -------
    dict
        delta_phi_earth_deg : 地球运动角度 (度)
        delta_theta_rocket_deg : 火箭轨道角度 (度)，对半周期为 π
        phasing_condition : 相位差（应为 2kπ 的倍数）
    """
    delta_phi_earth = (2.0 * np.pi) * dt_flight_days / T_earth_days

    # 对半周期飞行，真近点角扫过 π (从远日点到近日点再到远日点)
    # 对全周期飞行，扫过 2π
    # 这里我们统一用半周期 π
    delta_theta_rocket = np.pi

    return {
        "delta_phi_earth_rad": delta_phi_earth,
        "delta_phi_earth_deg": rad_to_deg(delta_phi_earth),
        "delta_theta_rocket_rad": delta_theta_rocket,
        "delta_theta_rocket_deg": rad_to_deg(delta_theta_rocket),
        "phase_mismatch_rad": delta_phi_earth - delta_theta_rocket,
    }


# =========================
# 开普勒方程求解
# =========================

def kepler_e(M: float, e: float, tol: float = 1e-12, max_iter: int = 100) -> float:
    """用牛顿法求解开普勒方程 M = E - e·sin(E)。

    适用于椭圆轨道 (0 <= e < 1)。

    Parameters
    ----------
    M : float
        平近点角 (rad)。
    e : float
        偏心率。
    tol : float, optional
        收敛容差。
    max_iter : int, optional
        最大迭代次数。

    Returns
    -------
    float
        偏近点角 E (rad)。
    """
    # 初值：对 M ≈ 0 或 e ≈ 1 取 E = M
    E = M
    for _ in range(max_iter):
        dE = (M - (E - e * np.sin(E))) / (1.0 - e * np.cos(E))
        E += dE
        if abs(dE) < tol:
            break
    return E


def true_from_eccentric(E: float, e: float) -> float:
    """由偏近点角 E 求真近点角 θ。

    tan(θ/2) = √((1+e)/(1-e)) · tan(E/2)
    """
    return 2.0 * np.arctan2(
        np.sqrt(1.0 + e) * np.sin(E / 2.0),
        np.sqrt(1.0 - e) * np.cos(E / 2.0),
    )


# =========================
# M1 回归测试
# =========================

def _run_m1_regression():
    """M1 回归测试：与钱书 r_p=0.2 AU 算例对比，偏差应 < 0.1%。"""
    print("=" * 66)
    print("M1 Regression: Patched Conic vs Qian's r_p=0.2 AU example")
    print("=" * 66)

    result = compute_patched_conic(r_p_AU=0.2)
    s = result.summary_dict()

    # 钱书参考值
    ref = {
        "a_AU": 0.6,
        "e": 0.6667,
        "p_AU": 0.3333,
        "v_1_kms": 17.21,
        "delta_v_kms": -12.59,
        "v_launch_kms": 16.84,
        "T_days": 169.8,
    }

    print(f"\n{'Parameter':<22} {'Computed':<16} {'Reference':<16} {'Rel.Err':<12}")
    print("-" * 66)

    max_rel_err = 0.0
    for key, ref_val in ref.items():
        comp_val = s[key]
        rel_err = abs((comp_val - ref_val) / ref_val)
        max_rel_err = max(max_rel_err, rel_err)
        flag = " <--" if rel_err > 0.001 else ""
        print(f"{key:<22} {comp_val:<16.6g} {ref_val:<16} {rel_err:<12.2e}{flag}")

    print("-" * 66)
    print(f"Max relative error: {max_rel_err:.2e}")
    assert max_rel_err < 0.001, f"M1 regression FAILED: max rel err = {max_rel_err:.2e} > 0.1%"
    print("M1 regression PASSED [OK]")
    return result


# =========================
# 主程序
# =========================

if __name__ == "__main__":
    result = _run_m1_regression()
    print(f"\n{result}")
