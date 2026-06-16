"""
trajectory.py
==============
单点轨道求解器 (Single-point Trajectory Solver).

整合 patched_conic + lunar_swingby + nbody，
对给定设计参数 (t₀, r_m, side, r_p) 计算完整的地球->月球借力->
飞近日点->返回地球轨道。

计算策略：
  S1: JPL 历表读取 Sun / Earth / Moon 在 t₀ 的状态
  S2: Patched conic -> 日心转移轨道元素
  S3: 地月转移段 - 将 v_inf 指向月球预测位置，N 体传播至近月点
  S4: 解析 swingby - 在近月点施加 Δv
  S5: 借力后日心段 - N 体传播至近日点并返回地球附近
  S6: 再入速度计算

参考系：J2000 黄道平面（二维投影）。
单位体系：km-s。
"""

import json
import os
from pathlib import Path
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Tuple, List

from constants import (
    GM_SUN, GM_EARTH, GM_MOON, AU_KM,
    R_SUN, R_EARTH, R_MOON,
    V_EARTH_ORBIT, V_ESCAPE_EARTH, V_MOON_ORBIT,
    R_MOON_ORBIT, R_MOON_SOI,
    DT_MAIN, DT_REFINE,
)
from units import day_to_sec, sec_to_day, km_to_au
from patched_conic import compute_patched_conic, OrbitalElements
from lunar_swingby import (
    compute_swingby, compute_swingby_turn_angle,
    compute_inf_dir_from_heliocentric,
    SwingbyResult,
)
from nbody import propagate_nbody, GM_SEMR, BODY_NAMES_R
from horizons import fetch_sem_vectors
from mission_constraints import validate_launch_mjd, is_total_flight_time_valid


# =========================
# 1. 设计参数与结果
# =========================

@dataclass
class DesignParams:
    """单点轨道设计参数。"""
    t0_mjd: float       # 发射时间 (MJD)
    r_m: float          # 近月距 (km)
    side: str           # "leading" 或 "trailing"
    r_p: float          # 设计近日距 (km)


@dataclass
class TrajectoryResult:
    """单点轨道完整求解结果。"""
    params: DesignParams

    # 发射时刻天体状态
    t0_mjd: float
    r_sun_t0: np.ndarray = field(default_factory=lambda: np.zeros(2), repr=False)
    r_earth_t0: np.ndarray = field(default_factory=lambda: np.zeros(2), repr=False)
    v_earth_t0: np.ndarray = field(default_factory=lambda: np.zeros(2), repr=False)
    r_moon_t0: np.ndarray = field(default_factory=lambda: np.zeros(2), repr=False)
    v_moon_t0: np.ndarray = field(default_factory=lambda: np.zeros(2), repr=False)

    # Patched conic 元素
    elements: Optional[OrbitalElements] = None
    v_launch: float = 0.0
    v_inf_earth: float = 0.0

    # 地月转移
    t_transfer_days: float = 0.0
    r_at_moon: np.ndarray = field(default_factory=lambda: np.zeros(2), repr=False)
    v_at_moon: np.ndarray = field(default_factory=lambda: np.zeros(2), repr=False)
    r_moon_at_encounter: np.ndarray = field(default_factory=lambda: np.zeros(2), repr=False)
    v_moon_at_encounter: np.ndarray = field(default_factory=lambda: np.zeros(2), repr=False)
    dist_moon_min: float = 0.0

    # 月球借力
    swingby: Optional[SwingbyResult] = None
    v_post_swingby: np.ndarray = field(default_factory=lambda: np.zeros(2), repr=False)

    # 日心段
    r_p_achieved_km: float = 0.0
    t_coast_days: float = 0.0
    r_final: np.ndarray = field(default_factory=lambda: np.zeros(2), repr=False)
    v_final: np.ndarray = field(default_factory=lambda: np.zeros(2), repr=False)
    r_earth_final: np.ndarray = field(default_factory=lambda: np.zeros(2), repr=False)
    v_earth_final: np.ndarray = field(default_factory=lambda: np.zeros(2), repr=False)

    # 再入
    v_rel_earth: float = 0.0
    v_reentry: float = 0.0
    t_total_days: float = 0.0

    # 状态
    success: bool = False
    error_message: str = ""

    def summary_dict(self) -> dict:
        dv = self.swingby.dv_mag if self.swingby else 0.0
        dd = self.swingby.delta_deg if self.swingby else 0.0
        return {
            "t0_mjd": self.t0_mjd,
            "r_m_km": self.params.r_m,
            "side": self.params.side,
            "r_p_design_AU": km_to_au(self.params.r_p),
            "r_p_achieved_AU": km_to_au(self.r_p_achieved_km),
            "v_launch_kms": self.v_launch,
            "v_inf_earth_kms": self.v_inf_earth,
            "t_transfer_days": self.t_transfer_days,
            "dist_moon_min_km": self.dist_moon_min,
            "swingby_dv_kms": dv,
            "swingby_delta_deg": dd,
            "t_coast_days": self.t_coast_days,
            "t_total_days": self.t_total_days,
            "v_reentry_kms": self.v_reentry,
            "success": self.success,
        }


# =========================
# 2. 历表插值
# =========================

def interpolate_state_at_mjd(
    body_data: dict, body_name: str, target_mjd: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """从 Horizons 缓存数据线性插值到指定 MJD。"""
    jd_arr = np.array(body_data[body_name]["jd_tdb"], dtype=float)
    mjd_arr = jd_arr - 2400000.5

    mjd_min = float(mjd_arr[0])
    mjd_max = float(mjd_arr[-1])
    if target_mjd < mjd_min or target_mjd > mjd_max:
        raise ValueError(
            f"{body_name} interpolation target MJD {target_mjd:.2f} is outside cached range "
            f"[{mjd_min:.2f}, {mjd_max:.2f}]"
        )

    x = np.array(body_data[body_name]["x_km"], dtype=float)
    y = np.array(body_data[body_name]["y_km"], dtype=float)
    vx = np.array(body_data[body_name]["vx_kms"], dtype=float)
    vy = np.array(body_data[body_name]["vy_kms"], dtype=float)

    idx = np.clip(np.searchsorted(mjd_arr, target_mjd), 1, len(mjd_arr) - 1)
    t0, t1 = mjd_arr[idx - 1], mjd_arr[idx]
    w = np.clip((target_mjd - t0) / (t1 - t0) if t1 > t0 else 0.0, 0.0, 1.0)

    r = np.array([(1 - w) * x[idx - 1] + w * x[idx],
                  (1 - w) * y[idx - 1] + w * y[idx]])
    v = np.array([(1 - w) * vx[idx - 1] + w * vx[idx],
                  (1 - w) * vy[idx - 1] + w * vy[idx]])
    return r, v


# =========================
# 3. 地月转移瞄准
# =========================

def estimate_moon_transfer(
    r_sun: np.ndarray, v_sun: np.ndarray,
    r_earth: np.ndarray, v_earth: np.ndarray,
    r_moon: np.ndarray, v_moon: np.ndarray,
    v_inf_mag: float,
    dt_integrate: float = DT_MAIN,
    max_search_days: float = 12.0,
    v_inf_dir: Optional[np.ndarray] = None,
) -> Tuple[float, list, list, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """地月转移段：用简单迭代法瞄准月球进行 N 体传播。

    思路：
      1. 预估一个转移时间（从简单弹道估算），计算月球在此时间后的位置
      2. 将火箭 v_inf 指向预估的月球拦截点
      3. 以 ~1 天为步长做 N 体传播，记录每步火箭-月球距离
      4. 在最近距离处记录状态

    Returns
    -------
    (t_transfer_s, r4, v4, r_rocket_closest, v_rocket_closest, r_moon_closest, v_moon_closest)
    """
    # === 地月转移初态 ===
    # 轨道设计方向由 patched conic 决定。
    # 对近日转移 (r_p < 1 AU)，火箭需要减速（逆地球公转方向发射），
    # v_inf 方向应逆地球速度方向。
    # 对远日转移 (r_p > 1 AU)，v_inf 方向顺地球速度方向。
    # 月球相遇由 N 体前向扫描自动寻找。

    r_parking = R_EARTH * 1.1                    # ~7016 km
    v_rel = np.sqrt(v_inf_mag**2 + 2.0 * GM_EARTH / r_parking)  # C3 修正
    gm4 = [GM_SUN, GM_EARTH, GM_MOON, 0.0]

    max_sec = min(max_search_days * 86400.0, 14 * 86400.0)

    def _rotate(vec: np.ndarray, angle_rad: float) -> np.ndarray:
        c = np.cos(angle_rad)
        s = np.sin(angle_rad)
        return np.array([c * vec[0] - s * vec[1], s * vec[0] + c * vec[1]])

    def _scan_direction(aim_dir: np.ndarray):
        r0_rocket = r_earth + r_parking * aim_dir
        v0_rocket = v_earth + v_rel * aim_dir
        r4 = [r_sun.copy(), r_earth.copy(), r_moon.copy(), r0_rocket.copy()]
        v4 = [v_sun.copy(), v_earth.copy(), v_moon.copy(), v0_rocket.copy()]

        best_dist = np.inf
        best_r4 = [ri.copy() for ri in r4]
        best_v4 = [vi.copy() for vi in v4]
        best_rocket_r = r0_rocket.copy()
        best_rocket_v = v0_rocket.copy()
        best_moon_r = r_moon.copy()
        best_moon_v = v_moon.copy()
        best_time = 0.0
        t_accum = 0.0

        while t_accum < max_sec:
            step = min(DT_MAIN, max_sec - t_accum)
            if step <= 0:
                break
            r4, v4 = propagate_nbody(r4, v4, step, gm4, n_bodies=4,
                                      dt_internal=DT_REFINE)
            t_accum += step

            r_rocket = r4[3]
            r_moon_now = r4[2]
            dist = np.linalg.norm(r_rocket - r_moon_now)

            if dist < best_dist:
                best_dist = dist
                best_r4 = [ri.copy() for ri in r4]
                best_v4 = [vi.copy() for vi in v4]
                best_rocket_r = r4[3].copy()
                best_rocket_v = v4[3].copy()
                best_moon_r = r4[2].copy()
                best_moon_v = v4[2].copy()
                best_time = t_accum

            # 早停：火箭已远离地月系统
            r_earth_now = r4[1]
            if np.linalg.norm(r_rocket - r_earth_now) > 2.0 * AU_KM:
                break

        return (
            best_dist, best_time, best_r4, best_v4,
            best_rocket_r, best_rocket_v, best_moon_r, best_moon_v, aim_dir
        )

    # 先用月球相对地球方向做粗瞄准，再用设计给出的 v_inf 方向做补充候选。
    moon_rel = r_moon - r_earth
    moon_u = moon_rel / (np.linalg.norm(moon_rel) + 1e-15)
    candidate_dirs = []
    for angle_deg in [-20.0, -10.0, -5.0, 0.0, 5.0, 10.0, 20.0]:
        candidate_dirs.append(_rotate(moon_u, np.deg2rad(angle_deg)))
    if v_inf_dir is not None:
        candidate_dirs.append(v_inf_dir / (np.linalg.norm(v_inf_dir) + 1e-15))
    else:
        candidate_dirs.append(-v_earth / (np.linalg.norm(v_earth) + 1e-15))

    best_pack = None
    for cand_dir in candidate_dirs:
        pack = _scan_direction(cand_dir / (np.linalg.norm(cand_dir) + 1e-15))
        if best_pack is None or pack[0] < best_pack[0]:
            best_pack = pack

    (best_dist, best_time, best_r4, best_v4,
     best_rocket_r, best_rocket_v, best_moon_r, best_moon_v, best_aim_dir) = best_pack

    # === 精化扫描：在最佳相遇附近用 DT_REFINE (60s) 重新传播 ===
    # 从最佳相遇时刻前 24h 重新出发，用细步长积分经过近月区域
    t_restart = max(best_time - 86400.0, 0.0)
    # 重建初态（从搜索起点前推）
    r0_rocket = r_earth + r_parking * best_aim_dir
    v0_rocket = v_earth + v_rel * best_aim_dir
    r4_refine = [r0s.copy() for r0s in [r_sun, r_earth, r_moon, r0_rocket]]
    v4_refine = [v0s.copy() for v0s in [v_sun, v_earth, v_moon, v0_rocket]]
    r4_refine, v4_refine = propagate_nbody(
        r4_refine, v4_refine, t_restart, gm4, n_bodies=4,
        dt_internal=DT_REFINE,
    )
    # 从 t_restart 到 best_time + 24h，用 DT_REFINE 步长
    t_extra = min(best_time + 86400.0, max_sec) - t_restart
    n_refine = max(int(t_extra / DT_REFINE), 1)
    best_dist2 = np.inf
    best_r4_r = r4_refine
    best_v4_r = v4_refine
    best_rocket_r_r = r4_refine[3].copy()
    best_rocket_v_r = v4_refine[3].copy()
    best_moon_r_r = r4_refine[2].copy()
    best_moon_v_r = v4_refine[2].copy()
    best_time2 = t_restart
    t_refine = t_restart
    for _ in range(n_refine):
        r4_refine, v4_refine = propagate_nbody(
            r4_refine, v4_refine, DT_REFINE, gm4, n_bodies=4,
            dt_internal=DT_REFINE,
        )
        t_refine += DT_REFINE
        dist = np.linalg.norm(r4_refine[3] - r4_refine[2])
        if dist < best_dist2:
            best_dist2 = dist
            best_r4_r = [ri.copy() for ri in r4_refine]
            best_v4_r = [vi.copy() for vi in v4_refine]
            best_rocket_r_r = r4_refine[3].copy()
            best_rocket_v_r = v4_refine[3].copy()
            best_moon_r_r = r4_refine[2].copy()
            best_moon_v_r = v4_refine[2].copy()
            best_time2 = t_refine
    # 如果精化扫描找到更近的距离，则采纳精化结果
    if best_dist2 < best_dist:
        best_r4 = best_r4_r
        best_v4 = best_v4_r
        best_rocket_r = best_rocket_r_r
        best_rocket_v = best_rocket_v_r
        best_moon_r = best_moon_r_r
        best_moon_v = best_moon_v_r
        best_dist = best_dist2
        best_time = best_time2

    return (best_time if best_dist < np.inf else t_accum, best_r4, best_v4,
            best_rocket_r, best_rocket_v, best_moon_r, best_moon_v)


# =========================
# 4. 主求解器
# =========================

def solve_trajectory(
    params: DesignParams,
    body_data: Optional[dict] = None,
    dt_integrate: float = DT_MAIN,
    verbose: bool = True,
) -> TrajectoryResult:
    """求解单点轨道。"""
    t0_mjd = params.t0_mjd
    validate_launch_mjd(t0_mjd, label="trajectory launch t0")

    # ---------- S1: 历表状态 ----------
    if body_data is None:
        body_data = fetch_sem_vectors(use_cache=True)

    r_sun, v_sun = interpolate_state_at_mjd(body_data, "Sun", t0_mjd)
    r_earth, v_earth = interpolate_state_at_mjd(body_data, "Earth", t0_mjd)
    r_moon, v_moon = interpolate_state_at_mjd(body_data, "Moon", t0_mjd)

    if verbose:
        print(f"\n[S1] t0 = MJD {t0_mjd:.2f}")
        print(f"  Earth-Moon dist = {np.linalg.norm(r_moon - r_earth):.0f} km")

    # ---------- S2: Patched conic 日心转移 ----------
    r_p_au = km_to_au(params.r_p)
    elements = compute_patched_conic(r_p_AU=r_p_au)

    # 日心转移所需 Δv (≈ -9.55 km/s 对于 r_p=0.3 AU)
    heliocentric_dv = abs(elements.delta_v)
    v_launch = elements.v_launch

    # 从 C3 公式计算地球逃逸双曲超额速度：
    #   C3 = v_launch² - 2·GM_EARTH / r_parking
    #   v_inf_earth = √C3
    # 其中 r_parking ≈ R_EARTH x 1.1 ≈ 7016 km
    r_parking = R_EARTH * 1.1  # ~7016 km
    c3 = v_launch**2 - 2.0 * GM_EARTH / r_parking
    v_inf_earth = np.sqrt(max(c3, 0.0))

    if verbose:
        print(f"\n[S2] Patched conic: r_p={r_p_au:.4f} AU, e={elements.e:.6f}, "
              f"heliocentric_dv={heliocentric_dv:.4f} km/s")
        print(f"  Lunar transfer v_inf (C3) = {v_inf_earth:.4f} km/s, "
              f"v_launch = {v_launch:.4f} km/s")

    # v_inf 方向：由 patched conic 的 delta_v 符号决定
    #   近日转移 (r_p < 1 AU, delta_v < 0) -> 逆地球速度方向 (retrograde)
    #   远日转移 (r_p > 1 AU, delta_v > 0) -> 顺地球速度方向 (prograde)
    earth_vel_dir = v_earth / np.linalg.norm(v_earth)
    if elements.delta_v < 0:
        v_inf_dir = -earth_vel_dir  # retrograde - 减速，向日内飞行
    else:
        v_inf_dir = earth_vel_dir   # prograde - 加速，向日外飞行

    if verbose:
        print(f"  v_inf direction: {'retrograde (decel)' if elements.delta_v < 0 else 'prograde (accel)'}")

    # ---------- S3: 地月转移 ----------
    if verbose:
        print(f"\n[S3] Earth-Moon transfer (aimed N-body sweep)")

    t_transfer, r4_mid, v4_mid, r_rocket_arrival, v_rocket_arrival, r_moon_arrival, v_moon_arrival = \
        estimate_moon_transfer(
            r_sun, v_sun, r_earth, v_earth, r_moon, v_moon,
            v_inf_earth, dt_integrate,
            v_inf_dir=v_inf_dir,
        )

    t_transfer_days = sec_to_day(t_transfer)
    dist_moon_min = np.linalg.norm(r_rocket_arrival - r_moon_arrival)  # closest to Moon

    if verbose:
        print(f"  Search time: {t_transfer_days:.2f} days")
        print(f"  Min rocket-Moon dist: {dist_moon_min:.0f} km")
        print(f"  Rocket |v| at closest: {np.linalg.norm(v_rocket_arrival):.4f} km/s")

    # ---------- S4: 月球借力 ----------
    if verbose:
        print(f"\n[S4] Lunar swingby")

    swingby_result = None
    v_post_swingby = v_rocket_arrival.copy()

    in_soi = dist_moon_min < R_MOON_SOI
    v_inf_mag, v_inf_dir = compute_inf_dir_from_heliocentric(
        v_rocket_arrival, v_moon_arrival
    )

    if verbose:
        print(f"  v_inf = {v_inf_mag:.4f} km/s (need > 0.1 km/s)")

    if in_soi and v_inf_mag > 0.1:
        try:
            swingby_result = compute_swingby(
                r_p=params.r_m,
                v_inf_mag=v_inf_mag,
                v_inf_dir_rad=v_inf_dir,
                v_moon=v_moon_arrival,
                side=params.side,
            )
            v_post_swingby = v_rocket_arrival + np.array([
                swingby_result.dv_x, swingby_result.dv_y
            ])
            if verbose:
                print(f"  delta={swingby_result.delta_deg:.4f} deg")
                print(f"  dv={swingby_result.dv_mag:.4f} km/s ({params.side})")
                print(f"  |v|: {np.linalg.norm(v_rocket_arrival):.4f} -> "
                      f"{np.linalg.norm(v_post_swingby):.4f} km/s")
        except Exception as e:
            if verbose:
                print(f"  Swingby calculation failed: {e}, skipping")
    else:
        if verbose:
            reason = ("outside Moon SOI" if not in_soi
                      else "v_inf too small")
            print(f"  Swingby skipped ({reason})")

    # ---------- S5: 日心段（近日点航行） ----------
    if verbose:
        print(f"\n[S5] Heliocentric coast")

    # 从月球附近继续传播
    r4_coast = [ri.copy() for ri in r4_mid]
    v4_coast = [vi.copy() for vi in v4_mid]
    r4_coast[3] = r_rocket_arrival.copy()
    v4_coast[3] = v_post_swingby.copy()

    t_coast = elements.dt_flight  # patched conic 预测的半周期 (s)
    t_coast_days = sec_to_day(t_coast)

    # 按天传播，追踪最小日心距
    n_days = max(int(np.ceil(t_coast / 86400.0)) + 1, 1)
    r_min_sun = np.inf

    for day in range(n_days):
        step = min(86400.0, t_coast - day * 86400.0)
        if step <= 0:
            break
        r4_coast, v4_coast = propagate_nbody(
            r4_coast, v4_coast, step, [GM_SUN, GM_EARTH, GM_MOON, 0.0],
            n_bodies=4, dt_internal=dt_integrate,
        )
        r_rocket_now = r4_coast[3]
        r_sun_now = r4_coast[0]
        dist_sun = np.linalg.norm(r_rocket_now - r_sun_now)
        if dist_sun < r_min_sun:
            r_min_sun = dist_sun

    r_rocket_final = r4_coast[3].copy()
    v_rocket_final = v4_coast[3].copy()
    r_earth_final = r4_coast[1].copy()
    v_earth_final = v4_coast[1].copy()

    dist_to_earth_final = np.linalg.norm(r_rocket_final - r_earth_final)
    t_total_days = sec_to_day(t_transfer + t_coast)
    if not is_total_flight_time_valid(t_total_days):
        raise ValueError(
            f"trajectory total flight time {t_total_days:.2f} days exceeds formal mission limit"
        )

    if verbose:
        print(f"  Coast: {t_coast_days:.2f} days")
        print(f"  Achieved perihelion: {km_to_au(r_min_sun):.4f} AU "
              f"({r_min_sun:.0f} km)")
        print(f"  Final rocket-Earth: {dist_to_earth_final:.0f} km")

    # ---------- S6: 再入速度 ----------
    v_rel_earth = np.linalg.norm(v_rocket_final - v_earth_final)
    v_reentry = np.sqrt(V_ESCAPE_EARTH ** 2 + v_rel_earth ** 2)

    if verbose:
        print(f"\n[S6] v_rel_earth = {v_rel_earth:.4f} km/s")
        print(f"      v_reentry   = {v_reentry:.4f} km/s")

    # ---------- 组装 ----------
    return TrajectoryResult(
        params=params,
        t0_mjd=t0_mjd,
        r_sun_t0=r_sun,
        r_earth_t0=r_earth,
        v_earth_t0=v_earth,
        r_moon_t0=r_moon,
        v_moon_t0=v_moon,
        elements=elements,
        v_launch=v_launch,
        v_inf_earth=v_inf_earth,
        t_transfer_days=t_transfer_days,
        r_at_moon=r_rocket_arrival,
        v_at_moon=v_rocket_arrival,
        r_moon_at_encounter=r_moon_arrival,
        v_moon_at_encounter=v_moon_arrival,
        dist_moon_min=dist_moon_min,
        swingby=swingby_result,
        v_post_swingby=v_post_swingby,
        r_p_achieved_km=r_min_sun if np.isfinite(r_min_sun) else params.r_p,
        t_coast_days=t_coast_days,
        r_final=r_rocket_final,
        v_final=v_rocket_final,
        r_earth_final=r_earth_final,
        v_earth_final=v_earth_final,
        v_rel_earth=v_rel_earth,
        v_reentry=v_reentry,
        t_total_days=t_total_days,
        success=True,
    )


# =========================
# 5. M5 回归测试
# =========================

def _run_m5_regression():
    """M5 回归测试。"""
    print("=" * 66)
    print("M5 Regression: Single-point Trajectory Solver")
    print("=" * 66)

    body_data = fetch_sem_vectors(use_cache=True)

    # MJD 61066 ≈ early Feb 2026 - the Moon is ~2deg off the retrograde
    # direction, giving good intercept geometry for an interior transfer.
    params = DesignParams(
        t0_mjd=61066.0,
        r_m=R_MOON + 500.0,
        side="trailing",
        r_p=0.3 * AU_KM,
    )

    print(f"\nParams: t0={params.t0_mjd:.1f} MJD, "
          f"r_m={params.r_m:.0f} km, side={params.side}, "
          f"r_p={km_to_au(params.r_p):.4f} AU")

    result = solve_trajectory(params, body_data, verbose=True)

    print(f"\n{'=' * 66}")
    print("Summary:")
    for k, v in result.summary_dict().items():
        print(f"  {k:<24} = {v}")

    # 写入诊断输出 (demand #6)
    debug_path = Path(__file__).resolve().parents[1] / "data" / "results" / "m5_debug.json"
    os.makedirs(debug_path.parent, exist_ok=True)
    debug_info = result.summary_dict()
    debug_info["r_p_rel_error"] = (
        abs(result.r_p_achieved_km - params.r_p) / params.r_p
        if params.r_p > 0 else -1.0
    )
    debug_info["r_m_design_km"] = params.r_m
    debug_info["r_p_design_km"] = params.r_p
    if result.swingby:
        debug_info["swingby_e"] = result.swingby.e
        debug_info["swingby_v_inf"] = result.swingby.v_inf
    with open(debug_path, "w", encoding="utf-8") as f:
        json.dump(debug_info, f, indent=2, ensure_ascii=False)
    print(f"\n[Debug] Diagnostic output saved to {debug_path}")

    assert result.success, f"Failed: {result.error_message}"
    assert result.v_launch > V_ESCAPE_EARTH, "v_launch too low"
    assert result.v_reentry > 0, "v_reentry invalid"
    assert np.isfinite(result.r_p_achieved_km), "r_p not finite"
    assert result.dist_moon_min < R_MOON_SOI, \
        f"Missed Moon SOI: {result.dist_moon_min:.0f} km (need < {R_MOON_SOI:.0f} km)"
    r_p_rel_error = abs(result.r_p_achieved_km - params.r_p) / params.r_p
    assert r_p_rel_error < 0.25, \
        f"Perihelion error too large: {r_p_rel_error:.2%} (design={km_to_au(params.r_p):.4f} AU, " \
        f"achieved={km_to_au(result.r_p_achieved_km):.4f} AU)"

    print(f"\nM5 regression PASSED [OK]")
    return result


if __name__ == "__main__":
    res = _run_m5_regression()
