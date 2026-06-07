"""
animation.py
=============
O5: 轨道动画生成 (Orbit Animation).

生成一段 30–60 秒的 MP4 轨道动画，展示火箭从地球出发、
经月球借力、飞越近日点后返回地球的完整过程。

关键事件标注 zoom-in：
  - 月球借力 (lunar swingby)
  - 近日点 (perihelion)
  - 返回地球 (Earth return)

单位体系：km-s（绘图时使用 AU）。
"""

import os
import numpy as np
from pathlib import Path
from typing import Optional

from constants import (
    GM_SUN, GM_EARTH, GM_MOON, AU_KM,
    R_MOON, R_MOON_SOI, R_MOON_ORBIT,
    DT_MAIN, DT_REFINE,
)
from units import km_to_au
from nbody import BODY_NAMES_R, GM_SEMR, vv_step_nbody
from trajectory import DesignParams, solve_trajectory
from horizons import fetch_sem_vectors, initial_state_from_horizons, state_at_index


def _ensure_animation_resources():
    """确保 matplotlib 动画后端可用，返回 plt 和 animation。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.animation as animation
    return plt, animation


def generate_orbit_animation(
    body_data: dict = None,
    t0_mjd: float = 61154.0,
    filename: str = "m8_orbit_animation.mp4",
    fps: int = 30,
    duration_sec: float = 45.0,
    dpi: int = 120,
    dt_frame: float = DT_MAIN,
) -> str:
    """生成完整日心轨道动画。

    Parameters
    ----------
    body_data : dict, optional
        Horizons 数据。
    t0_mjd : float
        最佳发射窗口 MJD（默认 61154.0）。
    filename : str
        输出 MP4 文件名。
    fps : int
        帧率，默认 30。
    duration_sec : float
        动画时长（秒），默认 45。
    dpi : int
        分辨率。
    dt_frame : float
        每帧对应的积分步长 (s)，默认 DT_MAIN=3600s。

    Returns
    -------
    str : MP4 文件路径。
    """
    plt, animation = _ensure_animation_resources()

    if body_data is None:
        body_data = fetch_sem_vectors(use_cache=True)

    # --- 获取初态 ---
    print("[Anim] Propagating full trajectory for animation...")

    # 在最佳窗口求解一次完整轨道，得到轨道参数
    params = DesignParams(
        t0_mjd=t0_mjd,
        r_m=R_MOON + 500.0,
        side="trailing",
        r_p=0.3 * AU_KM,
    )
    result = solve_trajectory(params, body_data, verbose=False)

    # 从历表重建日地月火箭四体初态
    r_sun3, v_sun3 = state_at_index(body_data, "Sun", 0)
    r_earth3, v_earth3 = state_at_index(body_data, "Earth", 0)
    r_moon3, v_moon3 = state_at_index(body_data, "Moon", 0)
    r_moon_t0 = result.r_moon_t0
    v_moon_t0 = result.v_moon_t0

    # 火箭初态：地月转移起点（接近地球）
    r_earth_t0 = result.r_earth_t0
    v_earth_t0 = result.v_earth_t0
    v_inf_dir = -v_earth_t0 / (np.linalg.norm(v_earth_t0) + 1e-15)
    r_parking = 7016.0
    r_rocket_t0 = r_earth_t0 + r_parking * v_inf_dir
    v_rocket_t0 = v_earth_t0 + result.v_inf_earth * v_inf_dir

    r4 = [r_sun3[:2], r_earth_t0, r_moon_t0, r_rocket_t0]
    v4 = [v_sun3[:2], v_earth_t0, v_moon_t0, v_rocket_t0]

    # --- 前向积分，记录全部历史 ---
    total_sec = result.t_total_days * 86400.0
    n_frames = int(duration_sec * fps)
    frame_interval = max(int(total_sec / (n_frames * dt_frame)), 1)
    n_steps = int(total_sec / dt_frame)

    r_hist = []
    t_hist = []
    r_min_sun = np.inf
    rocket_closest_moon = np.inf
    r_moon_hist = []
    r_earth_hist = []

    for step in range(n_steps):
        r4, v4 = vv_step_nbody(r4, v4, dt_frame, GM_SEMR, 4)
        t_now = (step + 1) * dt_frame

        if step % frame_interval == 0:
            r_hist.append([ri.copy() for ri in r4])
            t_hist.append(t_now)

        # 追踪近月点和近日点
        moon_d = np.linalg.norm(r4[3] - r4[2])
        if moon_d < rocket_closest_moon:
            rocket_closest_moon = moon_d
        sun_d = np.linalg.norm(r4[3] - r4[0])
        if sun_d < r_min_sun:
            r_min_sun = sun_d

    print(f"[Anim] Recorded {len(r_hist)} frames, "
          f"r_p_achieved={km_to_au(r_min_sun):.4f} AU, "
          f"Moon dist min={rocket_closest_moon:.0f} km")

    # 提取完整地月轨道（用于背景绘制）
    earth_x = km_to_au(np.array(body_data["Earth"]["x_km"], dtype=float))
    earth_y = km_to_au(np.array(body_data["Earth"]["y_km"], dtype=float))
    moon_x = km_to_au(np.array(body_data["Moon"]["x_km"], dtype=float))
    moon_y = km_to_au(np.array(body_data["Moon"]["y_km"], dtype=float))

    # 坐标转换：km → AU
    r_hist_au = []
    for state in r_hist:
        r_hist_au.append([km_to_au(ri) for ri in state])

    # --- 创建动画 ---
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.set_aspect("equal")

    r_p_AU = km_to_au(r_min_sun)
    max_ext = max(1.2, r_p_AU * 1.5)
    ax.set_xlim(-max_ext, max_ext)
    ax.set_ylim(-max_ext, max_ext)
    ax.set_xlabel("X (AU)")
    ax.set_ylabel("Y (AU)")
    ax.set_title("Earth → Moon → Perihelion → Earth")
    ax.grid(True, alpha=0.3)

    # 静态背景
    sun_dot = ax.scatter(0, 0, s=150, c="gold", edgecolors="orange", zorder=5, label="Sun")
    earth_orbit_line, = ax.plot([], [], "b--", linewidth=0.5, alpha=0.3, label="Earth orbit")
    moon_orbit_line, = ax.plot([], [], "gray", linewidth=0.2, alpha=0.2, label="Moon orbit")
    earth_orbit_line.set_data(earth_x, earth_y)
    moon_orbit_line.set_data(moon_x, moon_y)

    # 动态元素
    earth_dot, = ax.plot([], [], "bo", markersize=6, label="Earth")
    moon_dot, = ax.plot([], [], "go", markersize=4, label="Moon")
    rocket_dot, = ax.plot([], [], "ro", markersize=5, label="Rocket")
    rocket_trail, = ax.plot([], [], "r-", linewidth=1.0, alpha=0.6)
    trail_len = min(200, len(r_hist_au))

    # 信息文本
    info_text = ax.text(0.02, 0.98, "", transform=ax.transAxes,
                        fontsize=8, verticalalignment="top",
                        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.8))

    def init():
        earth_dot.set_data([], [])
        moon_dot.set_data([], [])
        rocket_dot.set_data([], [])
        rocket_trail.set_data([], [])
        info_text.set_text("")
        return earth_dot, moon_dot, rocket_dot, rocket_trail, info_text

    def animate(i):
        state = r_hist_au[i]
        r_s, r_e, r_m, r_r = state

        earth_dot.set_data([r_e[0]], [r_e[1]])
        moon_dot.set_data([r_m[0]], [r_m[1]])
        rocket_dot.set_data([r_r[0]], [r_r[1]])

        # 火箭轨迹尾迹
        start = max(0, i - trail_len)
        trail = r_hist_au[start:i + 1]
        trail_x = [s[3][0] for s in trail]
        trail_y = [s[3][1] for s in trail]
        rocket_trail.set_data(trail_x, trail_y)

        t_days = t_hist[i] / 86400.0
        info_text.set_text(
            f"Day {t_days:.1f}\n"
            f"Rocket-Sun: {np.linalg.norm(r_r - r_s):.4f} AU\n"
            f"Rocket-Moon: {np.linalg.norm(r_r - r_m) * AU_KM:.0f} km"
        )
        return earth_dot, moon_dot, rocket_dot, rocket_trail, info_text

    n_frames_actual = min(len(r_hist_au), n_frames)
    anim = animation.FuncAnimation(
        fig, animate, frames=n_frames_actual,
        init_func=init, blit=True, interval=1000.0 / fps,
    )

    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    path = out_dir / filename

    print(f"[Anim] Writing animation to {path} "
          f"({n_frames_actual} frames, {fps} fps)...")

    # 检测 ffmpeg，否则降级为 GIF (Pillow)
    import shutil
    if shutil.which("ffmpeg") is not None:
        anim.save(path, fps=fps, dpi=dpi, writer="ffmpeg",
                  extra_args=["-vcodec", "libx264", "-pix_fmt", "yuv420p"])
    else:
        # 降级为 GIF
        gif_path = path.with_suffix(".gif")
        print(f"[Anim] ffmpeg not found, writing GIF instead: {gif_path}")
        anim.save(gif_path, fps=fps, dpi=dpi, writer="pillow")
        path = gif_path

    plt.close(fig)
    print(f"[Anim] Saved animation to {path}")
    return str(path)


if __name__ == "__main__":
    generate_orbit_animation()
