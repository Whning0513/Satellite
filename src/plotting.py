"""
plotting.py
============
M8: 可视化模块 (Visualization).

功能：
  1. 轨迹图 - 显示太阳、地球、月球轨道及火箭路径
  2. 月球借力图 - 局部放大近月段轨迹
  3. 发射窗口极坐标图 - 全年 Moon 对准角分布
  4. 灵敏度分析图 - 参数扰动对近日距的影响
  5. 结果汇总图 - 整合上述图为一张综合报告图

参考系：J2000 黄道平面（二维投影）。
单位体系：km-s（绘图时内部使用 AU 以便显示）。
"""

import json
import os
import numpy as np
from pathlib import Path
from typing import Optional, List, Tuple

from constants import (
    GM_SUN, GM_EARTH, GM_MOON, AU_KM,
    R_SUN, R_EARTH, R_MOON, R_MOON_SOI, R_MOON_ORBIT,
    DT_MAIN, DT_REFINE, ENERGY_TOL,
)
from units import km_to_au, au_to_km, day_to_sec, sec_to_day
from trajectory import DesignParams, solve_trajectory, interpolate_state_at_mjd
from nbody import propagate_nbody
from horizons import fetch_sem_vectors
from optimize_window import scan_launch_window


def _ensure_matplotlib():
    """惰性导入 matplotlib，避免无 GUI 环境报错。"""
    import matplotlib
    matplotlib.use("Agg")  # 非交互式后端，适合保存文件
    import matplotlib.pyplot as plt
    return plt


# =========================
# 1. 基础轨道绘图
# =========================

def plot_trajectory(
    result,
    body_data: dict,
    filename: str = "trajectory.png",
    dpi: int = 150,
    show_earth_moon: bool = True,
) -> str:
    """绘制完整轨道图（日心系）。

    包括：太阳（黄色圆）、地球轨道（蓝色虚线）、
    月球轨道（灰色细线）、火箭路径（红色实线）。

    Parameters
    ----------
    result : TrajectoryResult
        solve_trajectory 的返回结果。
    body_data : dict
        Horizons 数据。
    filename : str
        保存文件名。
    dpi : int
        输出分辨率。
    show_earth_moon : bool
        是否绘制地球和月球轨道。

    Returns
    -------
    str : 图像保存路径。
    """
    plt = _ensure_matplotlib()

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_aspect("equal")

    # 标称太阳半径（绘图用放大比例）
    sun_r_plot = 0.02  # AU - 可视化放大

    # 太阳
    ax.scatter(0, 0, s=200, c="gold", edgecolors="orange", zorder=5, label="Sun")
    sun_circle = plt.Circle((0, 0), sun_r_plot, fill=False,
                            edgecolor="orange", linewidth=0.5, alpha=0.3)
    ax.add_patch(sun_circle)

    # 从历表数据绘制地球轨道
    if show_earth_moon:
        earth_x = km_to_au(np.array(body_data["Earth"]["x_km"], dtype=float))
        earth_y = km_to_au(np.array(body_data["Earth"]["y_km"], dtype=float))
        ax.plot(earth_x, earth_y, "b--", linewidth=0.8, alpha=0.5, label="Earth orbit")

        # 月球轨道（相对太阳 ≈ 地球轨道 + 小偏移）
        moon_x = km_to_au(np.array(body_data["Moon"]["x_km"], dtype=float))
        moon_y = km_to_au(np.array(body_data["Moon"]["y_km"], dtype=float))
        ax.plot(moon_x, moon_y, "gray", linewidth=0.3, alpha=0.3, label="Moon orbit")

        # 标记当前地月位置
        r_earth_t0 = km_to_au(result.r_earth_t0)
        r_moon_t0 = km_to_au(result.r_moon_t0)
        ax.scatter(*r_earth_t0, c="blue", s=50, marker="o", zorder=4, label="Earth @ t0")
        ax.scatter(*r_moon_t0, c="gray", s=30, marker="o", zorder=4, label="Moon @ t0")

    # 绘制火箭轨迹（使用 N 体传播重建路径，或从 result 的历史重建）
    # 由于 Result 不保存完整历史，这里从地月转移开始重新传播并记录历史
    params = result.params

    # 简化的火箭轨迹：从 patched conic 转移轨道绘制
    # 用半椭圆近似
    r_p = km_to_au(params.r_p)
    r_1 = 1.0  # 1 AU
    a = 0.5 * (r_1 + r_p)
    e = 1.0 - r_p / a

    theta = np.linspace(0, np.pi, 200)
    r_orbit = a * (1 - e ** 2) / (1 + e * np.cos(theta))
    x_orbit = r_orbit * np.cos(theta)
    y_orbit = r_orbit * np.sin(theta)

    # 对于内转移 (r_p < 1 AU)，轨迹在 x 负半轴
    if result.elements and result.elements.delta_v < 0:
        x_orbit = -x_orbit

    ax.plot(x_orbit, y_orbit, "r-", linewidth=1.5, alpha=0.8, label="Transfer orbit (patched conic)")

    # 标记近日点
    r_p_achieved = km_to_au(result.r_p_achieved_km)
    ax.scatter(-r_p_achieved if result.elements and result.elements.delta_v < 0 else r_p_achieved,
               0, c="red", s=80, marker="*", zorder=6, label=f"Perihelion ({r_p_achieved:.3f} AU)")

    # 标记近月点
    r_moon_arrival = km_to_au(result.r_at_moon)
    ax.scatter(*r_moon_arrival, c="purple", s=60, marker="^", zorder=5,
               label=f"Moon flyby ({result.dist_moon_min:.0f} km)")

    # 标注信息
    info_text = (
        f"t0 = MJD {result.t0_mjd:.1f}\n"
        f"v_launch = {result.v_launch:.2f} km/s\n"
        f"r_p = {r_p_achieved:.4f} AU\n"
        f"v_reentry = {result.v_reentry:.2f} km/s\n"
        f"T_total = {result.t_total_days:.1f} days"
    )
    ax.text(0.02, 0.98, info_text, transform=ax.transAxes,
            fontsize=9, verticalalignment="top",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.8))

    ax.set_xlabel("X (AU)")
    ax.set_ylabel("Y (AU)")
    ax.set_title("Space Trajectory: Earth -> Moon Swingby -> Perihelion -> Earth")
    ax.legend(loc="lower left", fontsize=8)
    ax.grid(True, alpha=0.3)

    # 设置适当的绘图范围
    max_extent = max(1.2, r_p_achieved * 1.5)
    ax.set_xlim(-max_extent, max_extent)
    ax.set_ylim(-max_extent, max_extent)

    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    path = out_dir / filename
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"[Plot] Saved trajectory plot to {path}")
    return str(path)


# =========================
# 2. 月球借力局部图
# =========================

def plot_lunar_swingby(
    result,
    filename: str = "lunar_swingby.png",
    dpi: int = 150,
) -> str:
    """绘制月球借力局部放大图。

    以月球为中心，绘制火箭在月球附近的轨迹、近月点、SOI 范围。
    """
    plt = _ensure_matplotlib()

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.set_aspect("equal")

    # 以月球位置为中心
    moon_center = km_to_au(result.r_at_moon)

    # SOI 圆
    soi_au = km_to_au(R_MOON_SOI)
    soi_circle = plt.Circle(moon_center, soi_au, fill=False,
                            edgecolor="gray", linewidth=0.5, linestyle="--", alpha=0.5,
                            label=f"Moon SOI ({R_MOON_SOI:.0f} km)")
    ax.add_patch(soi_circle)

    # 月球表面（放大显示）
    moon_r_au = km_to_au(R_MOON)
    moon_circle = plt.Circle(moon_center, moon_r_au, fill=True,
                             facecolor="lightgray", edgecolor="gray", alpha=0.8,
                             label="Moon")
    ax.add_patch(moon_circle)

    # 近月点标记
    ax.scatter(*moon_center, c="purple", s=80, marker="^", zorder=5,
               label=f"Closest approach ({result.dist_moon_min:.0f} km)")

    # 火箭到达 / 离开方向（箭头示意）
    v_arrival = km_to_au(result.v_at_moon) * 0.01  # 缩放箭头
    arrival_dir = v_arrival / np.linalg.norm(v_arrival) * soi_au * 0.8
    ax.arrow(moon_center[0] - arrival_dir[0],
             moon_center[1] - arrival_dir[1],
             arrival_dir[0] * 0.9, arrival_dir[1] * 0.9,
             head_width=soi_au * 0.08, color="red", alpha=0.7,
             label="Rocket arrival")

    if result.swingby:
        v_depart = km_to_au(result.v_post_swingby) * 0.01
        depart_dir = v_depart / np.linalg.norm(v_depart) * soi_au * 0.8
        ax.arrow(moon_center[0] - depart_dir[0],
                 moon_center[1] - depart_dir[1],
                 depart_dir[0] * 0.9, depart_dir[1] * 0.9,
                 head_width=soi_au * 0.08, color="orange", alpha=0.7,
                 label="Rocket departure")

    # 显示 swingby 参数
    if result.swingby:
        info = (
            f"v_inf = {result.swingby.v_inf:.2f} km/s\n"
            f"delta = {result.swingby.delta_deg:.1f} deg\n"
            f"dv = {result.swingby.dv_mag:.2f} km/s\n"
            f"r_p_moon = {result.params.r_m:.0f} km\n"
            f"side = {result.params.side}"
        )
        ax.text(0.02, 0.98, info, transform=ax.transAxes,
                fontsize=9, verticalalignment="top",
                bbox=dict(boxstyle="round", facecolor="lightyellow", alpha=0.9))

    ax.set_xlabel("X (AU)")
    ax.set_ylabel("Y (AU)")
    ax.set_title("Lunar Swingby Detail")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(True, alpha=0.3)

    # 缩放至 SOI 范围
    ax.set_xlim(moon_center[0] - soi_au * 1.2, moon_center[0] + soi_au * 1.2)
    ax.set_ylim(moon_center[1] - soi_au * 1.2, moon_center[1] + soi_au * 1.2)

    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    path = out_dir / filename
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"[Plot] Saved lunar swingby plot to {path}")
    return str(path)


# =========================
# 3. 发射窗口极坐标图
# =========================

def plot_launch_windows(
    optimization_result,
    filename: str = "launch_windows.png",
    dpi: int = 150,
) -> str:
    """绘制全年 Moon 对准角雷达图。

    以日期为角度轴，对准角为半径，直观展示发射窗口分布。
    """
    plt = _ensure_matplotlib()

    windows = optimization_result.windows
    if not windows:
        print("[Plot] No window data to plot")
        return ""

    fig, ax = plt.subplots(figsize=(10, 8), subplot_kw={"projection": "polar"})

    # 提取数据
    angles = []
    radii = []
    colors = []

    for w in windows:
        # 角度：将 MJD 映射到 0-2π
        day_of_year = w.t0_mjd - int(w.t0_mjd)  # fallback to fractional
        # 用实际 MJD 计算角度
        angle = 2 * np.pi * (w.t0_mjd - windows[0].t0_mjd) / 365.0
        angles.append(angle)

        # 半径：对准角（deg），90deg = 最差
        radii.append(min(w.moon_angle_deg / 90.0, 1.0))
        colors.append("green" if w.feasible else "red")

    ax.scatter(angles, radii, c=colors, s=10, alpha=0.6)

    # 季度标记
    season_labels = ["Jan", "Apr", "Jul", "Oct"]
    season_angles = [0, np.pi/2, np.pi, 3*np.pi/2]
    ax.set_xticks(season_angles)
    ax.set_xticklabels(season_labels)

    ax.set_ylim(0, 1.0)
    ax.set_yticklabels(["0deg", "22.5deg", "45deg", "67.5deg", "90deg"])
    ax.set_title("Launch Window Alignment (2026)\nGreen=feasible, Red=marginal", va="bottom")

    # 标注最佳窗口
    if optimization_result.best_windows:
        best = optimization_result.best_windows[0]
        best_angle = 2 * np.pi * (best.t0_mjd - windows[0].t0_mjd) / 365.0
        ax.annotate(
            f"Best: MJD {best.t0_mjd:.0f}\n({best.moon_angle_deg:.1f}deg)",
            xy=(best_angle, best.moon_angle_deg / 90.0),
            xytext=(best_angle + 0.3, best.moon_angle_deg / 90.0 + 0.1),
            fontsize=8,
            arrowprops=dict(arrowstyle="->", color="blue"),
            bbox=dict(boxstyle="round", facecolor="lightblue", alpha=0.7),
        )

    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    path = out_dir / filename
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"[Plot] Saved launch window plot to {path}")
    return str(path)


# =========================
# 4. 灵敏度分析图
# =========================

def plot_sensitivity(
    sensitivity_result,
    filename: str = "sensitivity.png",
    dpi: int = 150,
) -> str:
    """绘制灵敏度散点图。

    横轴：参数类型，纵轴：r_p_achieved (AU)，不同颜色表示不同参数。
    """
    plt = _ensure_matplotlib()

    points = sensitivity_result.points
    if not points:
        print("[Plot] No sensitivity data to plot")
        return ""

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    # 分组
    t0_pts = [p for p in points if "t0" in p.label and p.success]
    rm_pts = [p for p in points if "r_m" in p.label and p.success]
    rp_pts = [p for p in points if "r_p" in p.label and p.success]
    mc_pts = [p for p in points if "mc_" in p.label and p.success]

    # t0 扰动子图
    ax = axes[0]
    if t0_pts:
        x = [p.perturbation for p in t0_pts]
        y = [p.r_p_achieved_AU for p in t0_pts]
        ax.scatter(x, y, c="blue", alpha=0.7)
        ax.axhline(y=sensitivity_result.nominal_r_p_achieved, color="gray",
                   linestyle="--", alpha=0.5, label=f"Nominal ({sensitivity_result.nominal_r_p_achieved:.4f} AU)")
        ax.set_xlabel("Δt₀ (days)")
        ax.set_ylabel("r_p (AU)")
        ax.set_title("t₀ Sensitivity")
        ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    # r_m 扰动子图
    ax = axes[1]
    if rm_pts:
        x = [p.perturbation for p in rm_pts]
        y = [p.r_p_achieved_AU for p in rm_pts]
        ax.scatter(x, y, c="green", alpha=0.7)
        ax.axhline(y=sensitivity_result.nominal_r_p_achieved, color="gray",
                   linestyle="--", alpha=0.5)
        ax.set_xlabel("Δr_m (km)")
        ax.set_title("r_m (Perilune) Sensitivity")
    ax.grid(True, alpha=0.3)

    # MC 直方图
    ax = axes[2]
    if mc_pts:
        rp_mc = [p.r_p_achieved_AU for p in mc_pts]
        ax.hist(rp_mc, bins=10, color="purple", alpha=0.7, edgecolor="black")
        ax.axvline(x=sensitivity_result.nominal_r_p_achieved, color="red",
                   linestyle="--", alpha=0.7, label=f"Nominal")
        ax.set_xlabel("r_p (AU)")
        ax.set_ylabel("Count")
        ax.set_title("Monte Carlo Distribution")
        ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    fig.suptitle("Sensitivity Analysis", fontsize=14)
    fig.tight_layout()

    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    path = out_dir / filename
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"[Plot] Saved sensitivity plot to {path}")
    return str(path)


# =========================
# 5. 诊断图：Horizons 残差、能量漂移、Δv 曲线、等值线
# =========================

def plot_horizons_residual(
    residuals_path: str = None,
    filename: str = "m8_horizons_residual.png",
    dpi: int = 150,
) -> str:
    """绘制 M3 位置残差时间序列（Sun/Earth/Moon + 6000 km 阈值）。

    Parameters
    ----------
    residuals_path : str, optional
        m3_residuals.json 的路径，默认 data/results/m3_residuals.json。
    filename : str
        保存文件名。
    dpi : int
        分辨率。

    Returns
    -------
    str : 图像保存路径。
    """
    plt = _ensure_matplotlib()

    if residuals_path is None:
        repo_root = Path(__file__).resolve().parents[1]
        residuals_path = repo_root / "data" / "results" / "m3_residuals.json"

    if not Path(residuals_path).exists():
        print(f"[Plot] Residuals file not found: {residuals_path}")
        return ""

    with open(residuals_path, "r") as f:
        rows = json.load(f)

    epochs = [r["epoch"] for r in rows]
    err_sun = [r.get("err_r_Sun_km", 0) or 0 for r in rows]
    err_earth = [r.get("err_r_Earth_km", 0) or 0 for r in rows]
    err_moon = [r.get("err_r_Moon_km", 0) or 0 for r in rows]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    # 位置残差
    threshold_km = 6000.0
    ax1.axhline(threshold_km, color="red", linestyle="--", linewidth=0.8,
                alpha=0.6, label=f"Threshold ({threshold_km:.0f} km)")
    ax1.plot(epochs, err_sun, label="Sun", alpha=0.8)
    ax1.plot(epochs, err_earth, label="Earth", alpha=0.8)
    ax1.plot(epochs, err_moon, label="Moon", alpha=0.8)
    ax1.set_ylabel("Position Error (km)")
    ax1.set_title("M3: N-body vs JPL Horizons — Daily Position Residuals")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)
    ax1.set_yscale("log")

    # 速度残差
    v_sun = [abs(r.get("err_v_Sun_kms", 0) or 0) for r in rows]
    v_earth = [abs(r.get("err_v_Earth_kms", 0) or 0) for r in rows]
    v_moon = [abs(r.get("err_v_Moon_kms", 0) or 0) for r in rows]
    ax2.plot(epochs, v_sun, label="Sun", alpha=0.8)
    ax2.plot(epochs, v_earth, label="Earth", alpha=0.8)
    ax2.plot(epochs, v_moon, label="Moon", alpha=0.8)
    ax2.set_xlabel("Epoch (day of year)")
    ax2.set_ylabel("Velocity Error (km/s)")
    ax2.set_title("Velocity Residuals")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    path = out_dir / filename
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"[Plot] Saved horizons residual plot to {path}")
    return str(path)


def plot_energy_drift(
    body_data: dict = None,
    filename: str = "m8_energy_drift.png",
    dpi: int = 150,
    n_days: int = 30,
) -> str:
    """对 Sun-Earth-Moon 三体做短期积分，监测能量/角动量相对漂移。

    Parameters
    ----------
    body_data : dict, optional
        Horizons 数据。
    filename : str
        保存文件名。
    dpi : int
    n_days : int
        积分天数（默认 30 天，足够观测漂移趋势）。

    Returns
    -------
    str : 图像保存路径。
    """
    plt = _ensure_matplotlib()

    if body_data is None:
        body_data = fetch_sem_vectors(use_cache=True)

    from nbody import propagate_nbody, compute_conserved_quantities, GM_SEM, BODY_NAMES
    from horizons import initial_state_from_horizons

    r0_list, v0_list = initial_state_from_horizons(body_data, 0)
    r = [ri.copy() for ri in r0_list]
    v = [vi.copy() for vi in v0_list]

    dt_step = DT_REFINE
    steps_per_day = int(86400.0 / dt_step)
    total_steps = n_days * steps_per_day

    E0, L0 = compute_conserved_quantities(r, v, GM_SEM, 3)

    energies, angmoms, t_hist = [], [], []
    for step in range(total_steps):
        r, v = propagate_nbody(r, v, dt_step, GM_SEM, n_bodies=3,
                                dt_internal=dt_step)
        if step % (steps_per_day // 4) == 0:  # ~4 samples per day
            E, L = compute_conserved_quantities(r, v, GM_SEM, 3)
            # L is (1,) or (3,); take norm
            L_norm = np.linalg.norm(L)
            energies.append(E)
            angmoms.append(L_norm)
            t_hist.append((step + 1) * dt_step / 86400.0)

    energies = np.array(energies)
    angmoms = np.array(angmoms)
    rel_de = abs((energies - E0) / E0)

    # L0 标量化
    if hasattr(L0, 'shape'):
        l0_norm = float(np.linalg.norm(L0))
    else:
        l0_norm = float(abs(L0))
    if l0_norm == 0:
        rel_dl = np.zeros_like(energies)
    else:
        rel_dl = abs((angmoms - l0_norm) / l0_norm)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

    ax1.axhline(ENERGY_TOL, color="red", linestyle="--", linewidth=0.8,
                alpha=0.5, label=f"Tol ({ENERGY_TOL:.0e})")
    ax1.plot(t_hist, rel_de, "b-", alpha=0.8)
    ax1.set_ylabel("|ΔE / E₀|")
    ax1.set_title(f"N-body Energy & Angular Momentum Drift ({n_days}-day)")
    ax1.set_yscale("log")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)

    ax2.plot(t_hist, rel_dl, "g-", alpha=0.8)
    ax2.set_xlabel("Time (days)")
    ax2.set_ylabel("|ΔL / L₀|")
    ax2.set_yscale("log")
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    path = out_dir / filename
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"[Plot] Saved energy drift plot to {path}")
    return str(path)


def plot_delta_v_launch_date(
    optimization_result=None,
    filename: str = "m8_delta_v_launch_date.png",
    dpi: int = 150,
) -> str:
    """绘制 Δv 随发射日期变化的曲线。

    Parameters
    ----------
    optimization_result : OptimizationResult, optional
        M6 扫描结果。
    filename : str
    dpi : int

    Returns
    -------
    str : 图像保存路径。
    """
    plt = _ensure_matplotlib()

    if optimization_result is None:
        # 用轻量级扫描获取数据
        from optimize_window import scan_launch_window
        body_data = fetch_sem_vectors(use_cache=True)
        optimization_result = scan_launch_window(
            r_p_AU=0.3, r_m_km=R_MOON + 500.0,
            side="trailing", mode="fast", verbose=False,
            body_data=body_data,
        )

    windows = optimization_result.windows
    if not windows:
        print("[Plot] No window data to plot")
        return ""

    # 提取：日期 vs 评分（score 反映 C3 + 几何质量 → Δv proxy）
    mjds = [w.t0_mjd for w in windows]
    scores = [w.score for w in windows]
    angles = [w.moon_angle_deg for w in windows]
    feasible = [w.feasible for w in windows]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    # 上部：评分 vs 日期
    ax1.scatter(mjds, scores, c=["green" if f else "red" for f in feasible],
                s=5, alpha=0.5)
    ax1.axhline(6.0, color="orange", linestyle="--", linewidth=0.8, alpha=0.5,
                label="Feasibility threshold")
    ax1.set_ylabel("Geometric Score (lower = better)")
    ax1.set_title("Launch Window Scan (2026) — Alignment Score")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)
    ax1.set_yscale("log")

    # 下部：Moon 对准角
    ax2.scatter(mjds, angles, c=["green" if f else "red" for f in feasible],
                s=5, alpha=0.5)
    ax2.axhline(65.0, color="orange", linestyle="--", linewidth=0.8, alpha=0.5,
                label="Feasibility threshold (65°)")
    ax2.set_xlabel("Launch Date (MJD)")
    ax2.set_ylabel("Moon Alignment Angle (deg)")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)

    # 标注最佳窗口
    if optimization_result.best_windows:
        best = optimization_result.best_windows[0]
        ax2.annotate(
            f"Best: MJD {best.t0_mjd:.0f}\n({best.moon_angle_deg:.1f}°)",
            xy=(best.t0_mjd, best.moon_angle_deg),
            xytext=(best.t0_mjd + 20, best.moon_angle_deg + 10),
            fontsize=8,
            arrowprops=dict(arrowstyle="->", color="blue"),
            bbox=dict(boxstyle="round", facecolor="lightblue", alpha=0.7),
        )

    fig.tight_layout()
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    path = out_dir / filename
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"[Plot] Saved Δv-launch-date plot to {path}")
    return str(path)


def plot_t0_rp_contour(
    filename: str = "m8_t0_rp_contour.png",
    dpi: int = 150,
) -> str:
    """绘制 t0-r_p 参数扫描的 Δv 等值线图。

    对 3 个发射日期 × 3 个近日距运行 M5，插值绘制等值线。
    """
    plt = _ensure_matplotlib()

    body_data = fetch_sem_vectors(use_cache=True)

    # 扫描网格：5 t0 × 5 r_p
    t0_scan = np.linspace(61066.0, 61154.0, 5)
    rp_scan = np.linspace(0.25, 0.35, 5)
    gm_rp_ach = np.zeros((len(t0_scan), len(rp_scan)))

    print(f"[Plot] Scanning t0 × r_p grid ({len(t0_scan)}×{len(rp_scan)})...")
    for i, t0 in enumerate(t0_scan):
        for j, rp in enumerate(rp_scan):
            try:
                params = DesignParams(
                    t0_mjd=t0, r_m=R_MOON + 500.0,
                    side="trailing", r_p=rp * AU_KM,
                )
                res = solve_trajectory(params, body_data, verbose=False)
                gm_rp_ach[i, j] = km_to_au(res.r_p_achieved_km) if res.success else 0.0
            except Exception:
                gm_rp_ach[i, j] = 0.0

    fig, ax = plt.subplots(figsize=(8, 6))

    # 网格插值
    from scipy.interpolate import RectBivariateSpline
    try:
        # 细网格
        t0_fine = np.linspace(min(t0_scan), max(t0_scan), 30)
        rp_fine = np.linspace(min(rp_scan), max(rp_scan), 30)
        interp = RectBivariateSpline(t0_scan, rp_scan, gm_rp_ach)
        z_fine = interp(t0_fine, rp_fine)

        extent = [min(rp_scan), max(rp_scan), min(t0_scan), max(t0_scan)]
        im = ax.imshow(z_fine, origin="lower", aspect="auto", extent=extent,
                       cmap="viridis", interpolation="bilinear")
        fig.colorbar(im, ax=ax, label="Achieved r_p (AU)")

        # 等值线
        cs = ax.contour(rp_fine, t0_fine, z_fine, levels=6, colors="white",
                        linewidths=0.8, alpha=0.6)
        ax.clabel(cs, inline=True, fontsize=8, fmt="%.3f")
    except Exception as e:
        print(f"  Contour interpolation failed: {e}")
        # 降级：散点
        for i, t0 in enumerate(t0_scan):
            for j, rp in enumerate(rp_scan):
                ax.scatter(rp, t0, c=gm_rp_ach[i, j], s=100,
                           cmap="viridis", vmin=0, vmax=0.4)
        ax.set_title("t0 × r_p Grid (raw, no interpolation)")

    ax.set_xlabel("Design r_p (AU)")
    ax.set_ylabel("Launch Date (MJD)")
    ax.set_title("t0 — r_p Parameter Scan: Achieved Perihelion")

    fig.tight_layout()
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    path = out_dir / filename
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"[Plot] Saved t0-rp contour plot to {path}")
    return str(path)


# =========================
# 6. 综合报告图
# =========================

def generate_report_plots(
    m5_result=None,
    m6_result=None,
    m7_result=None,
    body_data: Optional[dict] = None,
    dpi: int = 150,
) -> List[str]:
    """生成所有报告所需图像。

    Parameters
    ----------
    m5_result : TrajectoryResult, optional
        M5 单点求解结果。
    m6_result : OptimizationResult, optional
        M6 窗口优化结果。
    m7_result : SensitivityResult, optional
        M7 灵敏度分析结果。
    body_data : dict, optional
        Horizons 数据。

    Returns
    -------
    List[str] : 所有生成的文件路径。
    """
    if body_data is None:
        body_data = fetch_sem_vectors(use_cache=True)

    generated = []

    # 如果未提供 M5 结果，运行一次 M5
    if m5_result is None:
        print("[Plot] Running M5 trajectory to generate plot data...")
        params = DesignParams(
            t0_mjd=61066.0,
            r_m=R_MOON + 500.0,
            side="trailing",
            r_p=0.3 * AU_KM,
        )
        m5_result = solve_trajectory(params, body_data, verbose=False)

    # 1. 轨道图
    p = plot_trajectory(m5_result, body_data, dpi=dpi)
    generated.append(p)

    # 2. 月球借力图
    p = plot_lunar_swingby(m5_result, dpi=dpi)
    generated.append(p)

    # 3. 发射窗口图
    if m6_result is not None:
        p = plot_launch_windows(m6_result, dpi=dpi)
        generated.append(p)

    # 4. 灵敏度图
    if m7_result is not None:
        p = plot_sensitivity(m7_result, dpi=dpi)
        generated.append(p)

    # 5. Horizons 残差图（从现有残差文件加载）
    p = plot_horizons_residual(dpi=dpi)
    generated.append(p)

    # 6. 能量漂移图
    p = plot_energy_drift(body_data, dpi=dpi)
    generated.append(p)

    # 7. Δv-发射日期曲线
    if m6_result is not None:
        p = plot_delta_v_launch_date(m6_result, dpi=dpi)
    else:
        p = plot_delta_v_launch_date(dpi=dpi)
    generated.append(p)

    return generated


# =========================
# 6. M8 回归测试
# =========================

def _run_m8_regression():
    """M8 回归测试：验证可视化模块。

    测试内容：
      1. 轨迹图生成（日心系）
      2. 月球借力局部图
      3. 发射窗口极坐标图
      4. 灵敏度分析图
      5. 所有图像写入 data/results/
    """
    print("=" * 66)
    print("M8 Regression: Visualization")
    print("=" * 66)

    try:
        _ = _ensure_matplotlib()
    except ImportError as e:
        print(f"  matplotlib not available ({e}), skipping M8")
        print("  Install with: pip install matplotlib")
        print(f"\nM8 regression SKIPPED [OK] (no matplotlib)")
        return

    body_data = fetch_sem_vectors(use_cache=True)
    dpi = 150

    # 运行 M5 获取轨迹数据
    print(f"\n--- Generating trajectory data (M5) ---")
    params = DesignParams(
        t0_mjd=61066.0,
        r_m=R_MOON + 500.0,
        side="trailing",
        r_p=0.3 * AU_KM,
    )
    m5_result = solve_trajectory(params, body_data, verbose=False)
    print(f"  r_p = {km_to_au(m5_result.r_p_achieved_km):.4f} AU")
    print(f"  Moon dist = {m5_result.dist_moon_min:.0f} km")

    # Test 1: 轨迹图
    print(f"\n--- Test 1: Full trajectory plot ---")
    p1 = plot_trajectory(m5_result, body_data, filename="m8_trajectory.png")
    assert Path(p1).exists(), f"Trajectory plot not created: {p1}"
    print(f"  OK: {p1}")

    # Test 2: 月球借力图
    print(f"\n--- Test 2: Lunar swingby detail ---")
    p2 = plot_lunar_swingby(m5_result, filename="m8_lunar_swingby.png")
    assert Path(p2).exists(), f"Swingby plot not created: {p2}"
    print(f"  OK: {p2}")

    # Test 3: 发射窗口图（运行快速扫描以获取数据）
    print(f"\n--- Test 3: Launch window polar plot ---")
    m6_result = scan_launch_window(
        r_p_AU=0.3, r_m_km=R_MOON + 500.0,
        side="trailing", mode="fast", verbose=False,
        body_data=body_data,
    )
    p3 = plot_launch_windows(m6_result, filename="m8_launch_windows.png")
    assert Path(p3).exists(), f"Window plot not created: {p3}"
    print(f"  OK: {p3}")

    # Test 4: 灵敏度图
    print(f"\n--- Test 4: Sensitivity plot ---")
    # 使用轻量级扰动替代完整 M7
    from sensitivity import (
        sweep_parameter, compute_sensitivity, SensitivityResult, SensitivityPoint
    )
    base_params = DesignParams(t0_mjd=61066.0, r_m=R_MOON+500, side="trailing", r_p=0.3*AU_KM)
    t0_pts = sweep_parameter("t0_mjd", 61066.0, [-1, 0, 1], base_params, body_data, verbose=False)
    rm_pts = sweep_parameter("r_m", R_MOON+500, [-500, 0, 500], base_params, body_data, verbose=False)
    rp_pts = sweep_parameter("r_p", 0.3*AU_KM, [-0.005*AU_KM, 0, 0.005*AU_KM], base_params, body_data, verbose=False)
    all_pts = t0_pts + rm_pts + rp_pts
    sens = compute_sensitivity(all_pts)
    m7_result = SensitivityResult(
        nominal_r_p_AU=km_to_au(0.3*AU_KM),
        nominal_t0_mjd=61066.0,
        nominal_r_m_km=R_MOON+500,
        nominal_side="trailing",
        nominal_success=True,
        nominal_v_launch=0, nominal_v_reentry=0, nominal_r_p_achieved=0.3,
        points=all_pts, sensitivity=sens,
    )
    p4 = plot_sensitivity(m7_result, filename="m8_sensitivity.png")
    assert Path(p4).exists(), f"Sensitivity plot not created: {p4}"
    print(f"  OK: {p4}")

    # Test 5: Horizons 残差图
    print(f"\n--- Test 5: Horizons residual plot ---")
    p5 = plot_horizons_residual(filename="m8_horizons_residual.png", dpi=dpi)
    assert Path(p5).exists(), f"Residual plot not created: {p5}"
    print(f"  OK: {p5}")

    # Test 6: 能量漂移图
    print(f"\n--- Test 6: Energy drift plot ---")
    p6 = plot_energy_drift(body_data, filename="m8_energy_drift.png", dpi=dpi, n_days=30)
    assert Path(p6).exists(), f"Energy drift plot not created: {p6}"
    print(f"  OK: {p6}")

    # Test 7: Δv-发射日期曲线
    print(f"\n--- Test 7: Delta-v vs launch date ---")
    p7 = plot_delta_v_launch_date(m6_result, filename="m8_delta_v_launch_date.png", dpi=dpi)
    assert Path(p7).exists(), f"Delta-v plot not created: {p7}"
    print(f"  OK: {p7}")

    # Test 8: t0-r_p 等值线图
    print(f"\n--- Test 8: t0-r_p contour ---")
    p8 = plot_t0_rp_contour(filename="m8_t0_rp_contour.png", dpi=dpi)
    assert Path(p8).exists(), f"Contour plot not created: {p8}"
    print(f"  OK: {p8}")

    print(f"\n{'='*66}")
    print(f"M8 regression PASSED [OK]")
    print(f"  Generated plots:")
    for p in [p1, p2, p3, p4, p5, p6, p7, p8]:
        size_kb = Path(p).stat().st_size / 1024
        print(f"    {Path(p).name} ({size_kb:.1f} KB)")
    return


# =========================
# 主程序
# =========================

if __name__ == "__main__":
    _run_m8_regression()
