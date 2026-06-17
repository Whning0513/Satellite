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
from typing import Optional, List, Tuple, Dict, Any

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
from budget_tools import ensure_lunar_row_formal_fields


def _ensure_matplotlib():
    """惰性导入 matplotlib，避免无 GUI 环境报错。"""
    import matplotlib
    matplotlib.use("Agg")  # 非交互式后端，适合保存文件
    import matplotlib.pyplot as plt
    return plt


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _results_dir() -> Path:
    return _repo_root() / "data" / "results"


def _save_figure(fig, filename: str, dpi: int) -> str:
    out_dir = _results_dir()
    os.makedirs(out_dir, exist_ok=True)
    path = out_dir / filename
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    return str(path)


def _load_result_json(filename: str) -> dict:
    path = _results_dir() / filename
    if not path.exists():
        raise FileNotFoundError(f"required result file missing: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_m7_sample_rows() -> List[dict]:
    data = _load_result_json("m7_extended_monte_carlo_samples.json")
    if isinstance(data, dict):
        return list(data.get("results", data.get("sample_rows", [])))
    return list(data)


def _extract_search_rows(search_result: Any) -> List[dict]:
    if isinstance(search_result, dict) and "search_rows" in search_result:
        return list(search_result.get("search_rows", []))
    if hasattr(search_result, "windows"):
        rows = []
        for w in getattr(search_result, "windows", []):
            rows.append({
                "t0_mjd": float(w.t0_mjd),
                "moon_angle_deg": float(getattr(w, "moon_angle_deg", np.nan)),
                "score": float(getattr(w, "score", np.nan)),
                "feasible": bool(getattr(w, "feasible", False)),
            })
        return rows
    return []


# =========================
# 1. 基础轨道绘图
# =========================

def plot_trajectory(
    result,
    body_data: dict,
    filename: str = "trajectory.png",
    dpi: int = 150,
    show_earth_moon: bool = True,
    formal_result: Optional[dict] = None,
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

    formal_result = formal_result or {}

    # 标记近日点
    r_p_achieved = float(formal_result.get("perihelion_AU", km_to_au(result.r_p_achieved_km)))
    ax.scatter(-r_p_achieved if result.elements and result.elements.delta_v < 0 else r_p_achieved,
               0, c="red", s=80, marker="*", zorder=6, label=f"Perihelion ({r_p_achieved:.3f} AU)")

    # 标记近月点
    r_moon_arrival = km_to_au(result.r_at_moon)
    ax.scatter(*r_moon_arrival, c="purple", s=60, marker="^", zorder=5,
               label=f"Moon flyby (sampled closest approach {result.dist_moon_min:.0f} km)")

    # 标注信息
    formal_return_vinf = formal_result.get("return_vinf_kms")
    formal_return_dist = formal_result.get("distance_to_earth_km")
    formal_result = ensure_lunar_row_formal_fields(formal_result or {})
    formal_budget = formal_result.get("dv_total_kms")
    supplementary_vinf_basis = formal_result.get("total_vinf_basis_kms")
    formal_t0 = formal_result.get("t0_mjd", result.t0_mjd)
    info_lines = [
        f"t0 = MJD {formal_t0:.1f}",
        f"v_launch = {result.v_launch:.2f} km/s",
        f"r_p = {r_p_achieved:.4f} AU",
    ]
    if formal_budget is not None:
        info_lines.append(f"formal total dv = {formal_budget:.4f} km/s")
    if supplementary_vinf_basis is not None:
        info_lines.append(f"supplementary vinf basis = {supplementary_vinf_basis:.4f} km/s")
    if formal_return_vinf is not None:
        info_lines.append(f"return vinf = {formal_return_vinf:.4f} km/s")
    if formal_return_dist is not None:
        info_lines.append(f"return distance = {formal_return_dist:.0f} km")
    info_lines.append(f"T_total = {result.t_total_days:.1f} days")
    info_text = "\n".join(info_lines)
    ax.text(0.02, 0.98, info_text, transform=ax.transAxes,
            fontsize=9, verticalalignment="top",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.8))

    ax.set_xlabel("X (AU)")
    ax.set_ylabel("Y (AU)")
    ax.set_title("Legal-Window Trajectory Geometry with Formal Earth-Return Annotation")
    ax.legend(loc="lower left", fontsize=8)
    ax.grid(True, alpha=0.3)

    # 设置适当的绘图范围
    max_extent = max(1.2, r_p_achieved * 1.5)
    ax.set_xlim(-max_extent, max_extent)
    ax.set_ylim(-max_extent, max_extent)

    path = _save_figure(fig, filename, dpi)
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
    formal_result: Optional[dict] = None,
) -> str:
    """绘制月球借力局部放大图。

    以月球为中心，绘制火箭在月球附近的轨迹、近月点、SOI 范围。
    """
    plt = _ensure_matplotlib()

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.set_aspect("equal")

    formal_result = formal_result or {}

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

    # 设计近月距与采样最小距离半径圈
    sampled_closest_au = km_to_au(result.dist_moon_min)
    design_r_m_au = km_to_au(result.params.r_m)
    sampled_circle = plt.Circle(
        moon_center, sampled_closest_au, fill=False,
        edgecolor="purple", linewidth=1.1, alpha=0.8,
        label=f"Sampled closest-approach radius ({result.dist_moon_min:.0f} km)",
    )
    design_circle = plt.Circle(
        moon_center, design_r_m_au, fill=False,
        edgecolor="royalblue", linewidth=0.9, linestyle=":",
        alpha=0.8, label=f"Design perilune radius ({result.params.r_m:.0f} km)",
    )
    ax.add_patch(sampled_circle)
    ax.add_patch(design_circle)

    # 火箭到达 / 离开方向（箭头示意）
    v_arrival = km_to_au(result.v_at_moon) * 0.01
    arrival_dir = v_arrival / np.linalg.norm(v_arrival) * soi_au * 0.22
    ax.arrow(moon_center[0] - arrival_dir[0],
             moon_center[1] - arrival_dir[1],
             arrival_dir[0] * 0.9, arrival_dir[1] * 0.9,
             head_width=soi_au * 0.03, color="red", alpha=0.75,
             label="Rocket arrival")

    if result.swingby:
        v_depart = km_to_au(result.v_post_swingby) * 0.01
        depart_dir = v_depart / np.linalg.norm(v_depart) * soi_au * 0.22
        ax.arrow(moon_center[0] - depart_dir[0],
                 moon_center[1] - depart_dir[1],
                 depart_dir[0] * 0.9, depart_dir[1] * 0.9,
                 head_width=soi_au * 0.03, color="orange", alpha=0.75,
                 label="Rocket departure")

    # 显示 swingby 参数
    if result.swingby:
        info_lines = [
            f"v_inf = {result.swingby.v_inf:.2f} km/s",
            f"delta = {result.swingby.delta_deg:.1f} deg",
            f"dv = {result.swingby.dv_mag:.2f} km/s",
            f"design r_m = {result.params.r_m:.0f} km",
            f"sampled min dist = {result.dist_moon_min:.0f} km",
            f"side = {result.params.side}",
        ]
        if formal_result.get("return_vinf_kms") is not None:
            info_lines.append(f"formal return vinf = {formal_result['return_vinf_kms']:.4f} km/s")
        info = "\n".join(info_lines)
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

    path = _save_figure(fig, filename, dpi)
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
    """绘制 2026 合法窗口分布图。"""
    plt = _ensure_matplotlib()

    rows = _extract_search_rows(optimization_result)
    if not rows:
        print("[Plot] No window data to plot")
        return ""

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    if "distance_to_earth_km" in rows[0]:
        valid_rows = [r for r in rows if r.get("valid_return_event")]
        fair_rows = [r for r in rows if r.get("fair")]
        invalid_rows = [r for r in rows if not r.get("valid_return_event")]

        if invalid_rows:
            ax1.scatter(
                [r["t0_mjd"] for r in invalid_rows],
                [max(1.0, float(r.get("distance_to_earth_km", np.nan))) for r in invalid_rows],
                c="lightcoral", s=10, alpha=0.35, label="Invalid / near-miss",
            )
        if valid_rows:
            ax1.scatter(
                [r["t0_mjd"] for r in valid_rows],
                [float(r["distance_to_earth_km"]) for r in valid_rows],
                c="darkorange", s=14, alpha=0.7, label="Valid return",
            )
        if fair_rows:
            ax1.scatter(
                [r["t0_mjd"] for r in fair_rows],
                [float(r["distance_to_earth_km"]) for r in fair_rows],
                c="forestgreen", s=18, alpha=0.85, label="Fair candidate",
            )
        ax1.axhline(1.5e6, color="red", linestyle="--", linewidth=0.9, alpha=0.6,
                    label="Earth-return threshold")
        ax1.set_ylabel("Return distance to Earth (km)")
        ax1.set_yscale("log")
        ax1.set_title("2026 Legal-Window Candidate Distribution")
        ax1.legend(fontsize=8)
        ax1.grid(True, alpha=0.3)

        ax2.scatter(
            [r["t0_mjd"] for r in rows],
            [float(r.get("perihelion_AU", np.nan)) for r in rows],
            c=["forestgreen" if r.get("fair") else ("darkorange" if r.get("valid_return_event") else "lightcoral")
               for r in rows],
            s=12, alpha=0.65,
        )
        ax2.axhline(0.3, color="navy", linestyle="--", linewidth=0.9, alpha=0.7,
                    label="Target perihelion 0.3 AU")
        ax2.set_xlabel("Launch Date (MJD)")
        ax2.set_ylabel("Achieved perihelion (AU)")
        ax2.legend(fontsize=8)
        ax2.grid(True, alpha=0.3)

        best = min(fair_rows or valid_rows, key=lambda r: float(r.get("distance_to_earth_km", np.inf))) if (fair_rows or valid_rows) else None
        if best:
            ax1.scatter([best["t0_mjd"]], [best["distance_to_earth_km"]], c="blue", s=40, marker="*",
                        zorder=6)
            ax1.annotate(
                f"Best legal candidate\nMJD {best['t0_mjd']:.1f}\nr_m={best['r_m_km']:.0f} km",
                xy=(best["t0_mjd"], best["distance_to_earth_km"]),
                xytext=(best["t0_mjd"] - 45, best["distance_to_earth_km"] * 3.5),
                fontsize=8,
                arrowprops=dict(arrowstyle="->", color="blue"),
                bbox=dict(boxstyle="round", facecolor="lightblue", alpha=0.8),
            )
    else:
        windows = optimization_result.windows
        angles = []
        radii = []
        colors = []
        for w in windows:
            angle = 2 * np.pi * (w.t0_mjd - windows[0].t0_mjd) / 365.0
            angles.append(angle)
            radii.append(min(w.moon_angle_deg / 90.0, 1.0))
            colors.append("green" if w.feasible else "red")
        plt.close(fig)
        fig, ax = plt.subplots(figsize=(10, 8), subplot_kw={"projection": "polar"})
        ax.scatter(angles, radii, c=colors, s=10, alpha=0.6)
        ax.set_xticks([0, np.pi / 2, np.pi, 3 * np.pi / 2])
        ax.set_xticklabels(["Jan", "Apr", "Jul", "Oct"])
        ax.set_ylim(0, 1.0)
        ax.set_title("Launch Window Alignment (legacy fast geometry)", va="bottom")
        path = _save_figure(fig, filename, dpi)
        plt.close(fig)
        print(f"[Plot] Saved launch window plot to {path}")
        return str(path)

    fig.tight_layout()
    path = _save_figure(fig, filename, dpi)
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
    """绘制当前 legal anchor 的 Monte Carlo 分布图。"""
    plt = _ensure_matplotlib()

    sample_rows = []
    summary = {}
    if isinstance(sensitivity_result, dict):
        sample_rows = list(sensitivity_result.get("results", sensitivity_result.get("sample_rows", [])))
        summary = sensitivity_result.get("summary", sensitivity_result)
    elif hasattr(sensitivity_result, "points"):
        sample_rows = list(getattr(sensitivity_result, "points", []))
    if not sample_rows:
        print("[Plot] No sensitivity data to plot")
        return ""

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    valid_rows = [ensure_lunar_row_formal_fields(r) for r in sample_rows if r.get("valid_return_event") and r.get("return_vinf_kms") is not None]
    invalid_rows = [r for r in sample_rows if not r.get("valid_return_event")]

    ax = axes[0]
    ret_vinf = [float(r["return_vinf_kms"]) for r in valid_rows]
    if ret_vinf:
        ax.hist(ret_vinf, bins=14, color="steelblue", alpha=0.8, edgecolor="black")
        p50 = summary.get("return_vinf_valid_only", {}).get("p50")
        p95 = summary.get("return_vinf_valid_only", {}).get("p95")
        if p50 is not None:
            ax.axvline(p50, color="navy", linestyle="--", linewidth=1.0, label=f"p50={p50:.2f}")
        if p95 is not None:
            ax.axvline(p95, color="crimson", linestyle=":", linewidth=1.0, label=f"p95={p95:.2f}")
        ax.legend(fontsize=8)
    ax.set_xlabel("Valid-only return vinf (km/s)")
    ax.set_ylabel("Count")
    ax.set_title("M7 Return vinf Distribution")
    ax.grid(True, alpha=0.3)

    ax = axes[1]
    total_dv = [float(r["dv_total_kms"]) for r in valid_rows if r.get("dv_total_kms") is not None]
    total_vinf = [float(r["total_vinf_basis_kms"]) for r in valid_rows if r.get("total_vinf_basis_kms") is not None]
    if total_dv or total_vinf:
        display_values = total_dv if total_dv else total_vinf
        ax.hist(display_values, bins=14, color="seagreen", alpha=0.8, edgecolor="black")
        p50 = summary.get("total_dv_valid_only", {}).get("p50")
        p95 = summary.get("total_dv_valid_only", {}).get("p95")
        if p50 is None:
            p50 = summary.get("total_vinf_basis_valid_only", {}).get("p50")
        if p95 is None:
            p95 = summary.get("total_vinf_basis_valid_only", {}).get("p95")
        if p50 is not None:
            ax.axvline(p50, color="darkgreen", linestyle="--", linewidth=1.0, label=f"p50={p50:.2f}")
        if p95 is not None:
            ax.axvline(p95, color="crimson", linestyle=":", linewidth=1.0, label=f"p95={p95:.2f}")
        ax.legend(fontsize=8)
    ax.set_xlabel(
        "Valid-only formal total dv (km/s)"
        if total_dv
        else "Valid-only supplementary total vinf basis (km/s)"
    )
    ax.set_title("M7 Total Budget Distribution")
    ax.grid(True, alpha=0.3)

    ax = axes[2]
    valid_dist = [float(r["event_distance_km"]) for r in valid_rows if r.get("event_distance_km") is not None]
    invalid_dist = [float(r["event_distance_km"]) for r in invalid_rows if r.get("event_distance_km") is not None]
    if valid_dist:
        ax.scatter([1] * len(valid_dist), valid_dist, c="forestgreen", s=12, alpha=0.5, label="Valid")
    if invalid_dist:
        ax.scatter([2] * len(invalid_dist), invalid_dist, c="lightcoral", s=12, alpha=0.5, label="Invalid")
    ax.axhline(1.5e6, color="red", linestyle="--", linewidth=0.9, alpha=0.7, label="Return threshold")
    ax.set_xticks([1, 2])
    ax.set_xticklabels(["Valid", "Invalid"])
    ax.set_yscale("log")
    ax.set_ylabel("Closest Earth distance (km)")
    ax.set_title("Earth-Return Event Distance")
    counts_text = (
        f"valid={len(valid_rows)}\n"
        f"invalid={len(invalid_rows)}\n"
        f"timeout={summary.get('timeout_count', 0)}"
    )
    ax.text(0.05, 0.95, counts_text, transform=ax.transAxes, va="top",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.8), fontsize=8)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    fig.suptitle("M7 Monte Carlo Diagnostics Around the Legal Fixed-Date Anchor", fontsize=14)
    fig.tight_layout()

    path = _save_figure(fig, filename, dpi)
    plt.close(fig)
    print(f"[Plot] Saved sensitivity plot to {path}")
    return str(path)


# =========================
# 5. 诊断图：Horizons 残差、能量漂移、dv 曲线、等值线
# =========================

def plot_horizons_residual(
    residuals_path: str = None,
    filename: str = "m8_horizons_residual.png",
    dpi: int = 150,
) -> str:
    """绘制 M3 same-source 对照图，优先用旧日残差，否则回退到深度审计结果。"""
    plt = _ensure_matplotlib()

    if residuals_path is None:
        residuals_path = _results_dir() / "m3_residuals.json"

    if Path(residuals_path).exists():
        with open(residuals_path, "r", encoding="utf-8") as f:
            rows = json.load(f)

        epochs = [r["epoch"] for r in rows]
        err_sun = [r.get("err_r_Sun_km", 0) or 0 for r in rows]
        err_earth = [r.get("err_r_Earth_km", 0) or 0 for r in rows]
        err_moon = [r.get("err_r_Moon_km", 0) or 0 for r in rows]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

        threshold_km = 6000.0
        ax1.axhline(threshold_km, color="red", linestyle="--", linewidth=0.8,
                    alpha=0.6, label=f"Threshold ({threshold_km:.0f} km)")
        ax1.plot(epochs, err_sun, label="Sun", alpha=0.8)
        ax1.plot(epochs, err_earth, label="Earth", alpha=0.8)
        ax1.plot(epochs, err_moon, label="Moon", alpha=0.8)
        ax1.set_ylabel("Position Error (km)")
        ax1.set_title("M3: N-body vs JPL Horizons Daily Position Residuals")
        ax1.legend(fontsize=8)
        ax1.grid(True, alpha=0.3)
        ax1.set_yscale("log")

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
    else:
        deep = _load_result_json("m3_numerical_deep_audit.json")
        models = deep.get("models", {})
        names = []
        residuals = []
        for key in ["3body_sun_earth_moon", "5body_sem_jupiter_venus", "full_planetary"]:
            block = models.get(key)
            if not block:
                continue
            names.append(key.replace("_", "\n"))
            residuals.append(float(block["residual_km"]))
        dt_rows = deep.get("dt_convergence", {}).get("values", [])

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
        ax1.bar(names, residuals, color=["steelblue", "seagreen", "darkorange"], alpha=0.85)
        ax1.axhline(6000.0, color="red", linestyle="--", linewidth=0.8, alpha=0.6, label="6000 km threshold")
        ax1.set_ylabel("Residual (km)")
        ax1.set_yscale("log")
        ax1.set_title("M3 Same-Source Residual Hierarchy")
        ax1.legend(fontsize=8)
        ax1.grid(True, alpha=0.3, axis="y")

        if dt_rows:
            ax2.plot([int(r["dt_sec"]) for r in dt_rows],
                     [float(r["residual_km"]) for r in dt_rows],
                     "o-", color="purple", alpha=0.85)
        ax2.set_xlabel("dt (s)")
        ax2.set_ylabel("3-body heliocentric residual (km)")
        ax2.set_title("Step-Size Convergence Interpretation")
        ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    path = _save_figure(fig, filename, dpi)
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
    """绘制 legal-window 搜索中预算与返回速度随日期变化。"""
    plt = _ensure_matplotlib()

    if optimization_result is None:
        optimization_result = _load_result_json("m5_legal_window_search.json")

    rows = [ensure_lunar_row_formal_fields(r) for r in _extract_search_rows(optimization_result)]
    if not rows:
        print("[Plot] No window data to plot")
        return ""

    valid_rows = [r for r in rows if r.get("valid_return_event") and r.get("dv_total_kms") is not None]
    fair_rows = [r for r in valid_rows if r.get("fair")]
    best = min(fair_rows or valid_rows, key=lambda r: float(r.get("distance_to_earth_km", np.inf)))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    ax1.scatter(
        [r["t0_mjd"] for r in valid_rows],
        [float(r["dv_total_kms"]) for r in valid_rows],
        c="darkorange", s=12, alpha=0.55, label="Valid return",
    )
    if fair_rows:
        ax1.scatter(
            [r["t0_mjd"] for r in fair_rows],
            [float(r["dv_total_kms"]) for r in fair_rows],
            c="forestgreen", s=16, alpha=0.8, label="Fair candidate",
        )
    ax1.scatter([best["t0_mjd"]], [best["dv_total_kms"]], c="blue", s=40, marker="*",
                zorder=5, label="Best legal candidate")
    ax1.set_ylabel("Formal total dv (km/s)")
    ax1.set_title("Legal-Window Budget and Return-Speed Diagnostics")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)

    return_rows = [r for r in valid_rows if r.get("return_vinf_kms") is not None]
    ax2.scatter(
        [r["t0_mjd"] for r in return_rows],
        [float(r["return_vinf_kms"]) for r in return_rows],
        c="slateblue", s=12, alpha=0.55, label="Valid return",
    )
    ax2.axhline(15.0, color="red", linestyle="--", linewidth=0.9, alpha=0.7,
                label="Mission threshold")
    ax2.set_xlabel("Launch Date (MJD)")
    ax2.set_ylabel("Return vinf (km/s)")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)
    ax2.annotate(
        f"Best: MJD {best['t0_mjd']:.1f}\nreturn dist={best['distance_to_earth_km']:.0f} km",
        xy=(best["t0_mjd"], best["return_vinf_kms"]),
        xytext=(best["t0_mjd"] - 55, best["return_vinf_kms"] + 1.1),
        fontsize=8,
        arrowprops=dict(arrowstyle="->", color="blue"),
        bbox=dict(boxstyle="round", facecolor="lightblue", alpha=0.7),
    )

    fig.tight_layout()
    path = _save_figure(fig, filename, dpi)
    plt.close(fig)
    print(f"[Plot] Saved dv-launch-date plot to {path}")
    return str(path)


def plot_t0_rp_contour(
    filename: str = "m8_t0_rp_contour.png",
    dpi: int = 150,
) -> str:
    """绘制 legal-window 搜索中 t0-r_m 的 achieved-perihelion 热图。"""
    plt = _ensure_matplotlib()
    search = _load_result_json("m5_legal_window_search.json")
    rows = [r for r in search.get("search_rows", []) if r.get("side") == "trailing"]
    if not rows:
        print("[Plot] No legal-window rows for contour plot")
        return ""

    t0_scan = sorted({float(r["t0_mjd"]) for r in rows})
    rm_scan = sorted({float(r["r_m_km"]) for r in rows})
    grid = np.full((len(rm_scan), len(t0_scan)), np.nan)

    t0_index = {v: i for i, v in enumerate(t0_scan)}
    rm_index = {v: i for i, v in enumerate(rm_scan)}
    for row in rows:
        grid[rm_index[float(row["r_m_km"])], t0_index[float(row["t0_mjd"])]] = float(row["perihelion_AU"])

    best = search.get("best_lunar_candidate")
    fig, ax = plt.subplots(figsize=(8, 6))
    extent = [min(t0_scan), max(t0_scan), min(rm_scan), max(rm_scan)]
    im = ax.imshow(grid, origin="lower", aspect="auto", extent=extent,
                   cmap="viridis", interpolation="nearest")
    fig.colorbar(im, ax=ax, label="Achieved perihelion (AU)")
    ax.set_xlabel("Launch Date (MJD)")
    ax.set_ylabel("r_m (km)")
    ax.set_title("Legal-Window t0-r_m Heatmap (trailing side)")
    if best:
        ax.scatter(best["t0_mjd"], best["r_m_km"], c="white", edgecolors="black", s=60, marker="*")
        ax.annotate(
            "Best legal candidate",
            xy=(best["t0_mjd"], best["r_m_km"]),
            xytext=(best["t0_mjd"] - 45, best["r_m_km"] + 1200),
            fontsize=8,
            arrowprops=dict(arrowstyle="->", color="white"),
            bbox=dict(boxstyle="round", facecolor="black", alpha=0.45),
            color="white",
        )

    fig.tight_layout()
    path = _save_figure(fig, filename, dpi)
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

    legal_window = _load_result_json("m5_legal_window_search.json")
    m6_independent = _load_result_json("m6_independent_window_search.json")
    m7_summary = _load_result_json("m7_extended_monte_carlo.json")
    m7_payload = {"summary": m7_summary, "results": _load_m7_sample_rows()}
    formal_candidate = m6_independent.get("best_valid_candidate") or legal_window.get("best_lunar_candidate")

    # 如果未提供 M5 结果，则用当前 legal-window formal 候选重建几何
    if m5_result is None and formal_candidate:
        print("[Plot] Reconstructing current legal-window trajectory geometry...")
        params = DesignParams(
            t0_mjd=float(formal_candidate["t0_mjd"]),
            r_m=float(formal_candidate["r_m_km"]),
            side=str(formal_candidate["side"]),
            r_p=0.3 * AU_KM,
        )
        m5_result = solve_trajectory(params, body_data, verbose=False)

    # 1. 轨道图
    p = plot_trajectory(m5_result, body_data, dpi=dpi, formal_result=formal_candidate)
    generated.append(p)

    # 2. 月球借力图
    p = plot_lunar_swingby(m5_result, dpi=dpi, formal_result=formal_candidate)
    generated.append(p)

    # 3. 发射窗口图
    p = plot_launch_windows(m6_result or legal_window, dpi=dpi)
    generated.append(p)

    # 4. 灵敏度图
    p = plot_sensitivity(m7_result or m7_payload, dpi=dpi)
    generated.append(p)

    # 5. Horizons 残差图（从现有残差文件加载）
    p = plot_horizons_residual(dpi=dpi)
    generated.append(p)

    # 6. 能量漂移图
    p = plot_energy_drift(body_data, dpi=dpi)
    generated.append(p)

    # 7. Δv-发射日期曲线
    p = plot_delta_v_launch_date(m6_result or legal_window, dpi=dpi)
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

    legal_window = _load_result_json("m5_legal_window_search.json")
    m6_independent = _load_result_json("m6_independent_window_search.json")
    m7_summary = _load_result_json("m7_extended_monte_carlo.json")
    m7_payload = {"summary": m7_summary, "results": _load_m7_sample_rows()}
    formal_candidate = m6_independent.get("best_valid_candidate") or legal_window.get("best_lunar_candidate")

    print(f"\n--- Generating trajectory data from current legal-window candidate ---")
    params = DesignParams(
        t0_mjd=float(formal_candidate["t0_mjd"]),
        r_m=float(formal_candidate["r_m_km"]),
        side=str(formal_candidate["side"]),
        r_p=0.3 * AU_KM,
    )
    m5_result = solve_trajectory(params, body_data, verbose=False)
    print(f"  formal perihelion = {formal_candidate['perihelion_AU']:.4f} AU")
    print(f"  Moon dist = {m5_result.dist_moon_min:.0f} km")

    # Test 1: 轨迹图
    print(f"\n--- Test 1: Full trajectory plot ---")
    p1 = plot_trajectory(
        m5_result, body_data, filename="m8_trajectory.png", formal_result=formal_candidate
    )
    assert Path(p1).exists(), f"Trajectory plot not created: {p1}"
    print(f"  OK: {p1}")

    # Test 2: 月球借力图
    print(f"\n--- Test 2: Lunar swingby detail ---")
    p2 = plot_lunar_swingby(
        m5_result, filename="m8_lunar_swingby.png", formal_result=formal_candidate
    )
    assert Path(p2).exists(), f"Swingby plot not created: {p2}"
    print(f"  OK: {p2}")

    # Test 3: 发射窗口图（使用正式 legal-window 搜索结果）
    print(f"\n--- Test 3: Legal-window candidate distribution ---")
    p3 = plot_launch_windows(legal_window, filename="m8_launch_windows.png")
    assert Path(p3).exists(), f"Window plot not created: {p3}"
    print(f"  OK: {p3}")

    # Test 4: M7 分布图
    print(f"\n--- Test 4: Monte Carlo distribution plot ---")
    p4 = plot_sensitivity(m7_payload, filename="m8_sensitivity.png")
    assert Path(p4).exists(), f"Sensitivity plot not created: {p4}"
    print(f"  OK: {p4}")

    # Test 5: Horizons 残差图
    print(f"\n--- Test 5: Horizons residual plot ---")
    p5 = plot_horizons_residual(filename="m8_horizons_residual.png", dpi=dpi)
    assert p5 and Path(p5).exists(), f"Residual plot not created: {p5}"
    print(f"  OK: {p5}")

    # Test 6: 能量漂移图
    print(f"\n--- Test 6: Energy drift plot ---")
    p6 = plot_energy_drift(body_data, filename="m8_energy_drift.png", dpi=dpi, n_days=30)
    assert Path(p6).exists(), f"Energy drift plot not created: {p6}"
    print(f"  OK: {p6}")

    # Test 7: legal-window 预算与返回速度曲线
    print(f"\n--- Test 7: Legal-window budget vs launch date ---")
    p7 = plot_delta_v_launch_date(legal_window, filename="m8_delta_v_launch_date.png", dpi=dpi)
    assert Path(p7).exists(), f"Delta-v plot not created: {p7}"
    print(f"  OK: {p7}")

    # Test 8: t0-r_m 热图
    print(f"\n--- Test 8: Legal-window t0-r_m heatmap ---")
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
