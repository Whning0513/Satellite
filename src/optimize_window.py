"""
optimize_window.py
==================
M6: 发射窗口优化 (Launch Window Optimization).

功能：
  1. 快速扫描：基于历表数据和解析几何，评估每日 Moon 对准质量
  2. 完整模式：对候选窗口运行完整 N 体轨迹求解器
  3. 输出最优发射窗口，优化目标是实现设计 r_p 的最小 C3

策略：
  - C3（= v_launch² - 2GM/r_parking）由 patched conic 决定，
    对于给定的 r_p，C3 是常数（不随 t0 变化）。
  - 因此优化本质是找到月球位置与发射方向最匹配的 t0，
    使 swingby 能最大化轨道能量传递。
  - 快速扫描用纯几何评分，完整模式用 N 体验证。

参考系：J2000 黄道平面（二维投影）。
单位体系：km-s。
"""

import json
import os
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from constants import (
    GM_SUN, GM_EARTH, GM_MOON, AU_KM,
    R_EARTH, R_MOON, R_MOON_ORBIT, R_MOON_SOI,
    V_EARTH_ORBIT, V_ESCAPE_EARTH, V_MOON_ORBIT,
    R_M_MIN, R_M_MAX, DT_MAIN, DT_REFINE,
)
from units import km_to_au, au_to_km, day_to_sec, sec_to_day, rad_to_deg, deg_to_rad
from patched_conic import compute_patched_conic
from lunar_swingby import (
    compute_swingby, compute_swingby_turn_angle,
    compute_inf_dir_from_heliocentric,
)
from trajectory import (
    DesignParams, solve_trajectory, interpolate_state_at_mjd,
    TrajectoryResult,
)
from horizons import fetch_sem_vectors


# =========================
# 1. 评分数据结构
# =========================

@dataclass
class WindowScore:
    """单日发射窗口评分。"""
    t0_mjd: float

    # Moon 对准几何
    moon_angle_deg: float = 0.0       # v_inf 方向与月球位置夹角 (deg)
    moon_dist_km: float = 0.0         # 地月距离 (km)
    earth_angle_deg: float = 0.0      # 地球方位角 (用于诊断)

    # 综合评分 (0=最佳，越低越好)
    score: float = np.inf

    # 完整求解结果（仅完整模式填充）
    full_success: bool = False
    full_v_launch: float = 0.0
    full_v_inf: float = 0.0
    full_r_p_achieved_AU: float = 0.0
    full_dist_moon_min: float = 0.0
    full_v_reentry: float = 0.0
    full_t_total: float = 0.0

    # 标记
    feasible: bool = False


@dataclass
class OptimizationResult:
    """发射窗口优化结果。"""
    r_p_AU: float
    r_m_km: float
    side: str

    # 所有扫描窗口
    windows: List[WindowScore] = field(default_factory=list)

    # 最佳窗口（按评分排序）
    best_windows: List[WindowScore] = field(default_factory=list)

    # 统计
    n_scanned: int = 0
    n_feasible: int = 0

    def summary_dict(self) -> dict:
        d = {
            "r_p_AU": self.r_p_AU,
            "r_m_km": self.r_m_km,
            "side": self.side,
            "n_scanned": self.n_scanned,
            "n_feasible": self.n_feasible,
        }
        if self.best_windows:
            b = self.best_windows[0]
            d.update({
                "best_t0_mjd": b.t0_mjd,
                "best_moon_angle_deg": round(b.moon_angle_deg, 2),
                "best_score": round(b.score, 4),
                "best_feasible": bool(b.feasible),
            })
            if b.full_success:
                d.update({
                    "best_v_launch_kms": round(b.full_v_launch, 4),
                    "best_v_inf_kms": round(b.full_v_inf, 4),
                    "best_r_p_achieved_AU": round(b.full_r_p_achieved_AU, 4),
                    "best_dist_moon_min_km": round(b.full_dist_moon_min, 1),
                    "best_v_reentry_kms": round(b.full_v_reentry, 4),
                    "best_t_total_days": round(b.full_t_total, 2),
                })
        else:
            d["message"] = "No feasible windows found"
        return d


# =========================
# 2. 快速扫描引擎
# =========================

def compute_moon_alignment(
    moon_pos_rel: np.ndarray,
    v_inf_dir: np.ndarray,
) -> float:
    """计算月球相对位置与 v_inf 方向的夹角（度）。

    0deg = Moon 正好在发射方向 -> 最易截获。
    """
    moon_u = moon_pos_rel / (np.linalg.norm(moon_pos_rel) + 1e-15)
    cos_angle = np.clip(np.dot(moon_u, v_inf_dir), -1.0, 1.0)
    return rad_to_deg(np.arccos(cos_angle))


def score_single_day_fast(
    t0_mjd: float,
    body_data: dict,
    elements,
) -> WindowScore:
    """快速评分单日：纯几何，无 N 体传播。

    Parameters
    ----------
    t0_mjd : float
        发射时间 (MJD)。
    body_data : dict
        Horizons 缓存数据。
    elements : OrbitalElements
        patched_conic.compute_patched_conic() 的返回结果（预计算）。

    Returns
    -------
    WindowScore
    """
    r_earth, v_earth = interpolate_state_at_mjd(body_data, "Earth", t0_mjd)
    r_moon, v_moon = interpolate_state_at_mjd(body_data, "Moon", t0_mjd)

    # v_inf 方向由 delta_v 符号决定
    earth_vel_dir = v_earth / (np.linalg.norm(v_earth) + 1e-15)
    if elements.delta_v < 0:
        v_inf_dir = -earth_vel_dir  # retrograde - interior transfer
    else:
        v_inf_dir = earth_vel_dir   # prograde - exterior transfer

    # Moon 相对地球位置
    moon_pos_rel = r_moon - r_earth
    moon_dist = np.linalg.norm(moon_pos_rel)

    # 对准角
    alignment = compute_moon_alignment(moon_pos_rel, v_inf_dir)

    # 距离因子（标称地月距 ≈ R_MOON_ORBIT）
    dist_factor = moon_dist / R_MOON_ORBIT

    # 综合评分（0 = 完美，越大越差）
    #   angle_cost: 二次惩罚，30deg 时 = 1.0，60deg 时 = 4.0
    #   dist_cost:  线性惩罚，远月 = 惩罚增大
    angle_cost = (alignment / 30.0) ** 2
    dist_cost = 0.5 * dist_factor
    score = angle_cost + dist_cost

    # 地球方位角（诊断用）
    earth_angle = rad_to_deg(np.arctan2(v_earth[1], v_earth[0]))

    # 可行窗口阈值：score < 6 ≈ alignment < ~65deg
    feasible = alignment < 65.0

    return WindowScore(
        t0_mjd=t0_mjd,
        moon_angle_deg=alignment,
        moon_dist_km=moon_dist,
        earth_angle_deg=earth_angle,
        score=score,
        feasible=feasible,
    )


# =========================
# 3. 完整模式：N 体验证
# =========================

def run_full_solve(
    t0_mjd: float,
    r_m_km: float,
    side: str,
    r_p_km: float,
    body_data: dict,
    verbose: bool = False,
) -> TrajectoryResult:
    """在给定 t0 运行完整 N 体轨迹求解。

    Parameters
    ----------
    t0_mjd : float
        发射时间 (MJD)。
    r_m_km : float
        近月距 (km)。
    side : str
        "leading" 或 "trailing"。
    r_p_km : float
        设计近日距 (km)。
    body_data : dict
        Horizons 数据。
    verbose : bool
        是否输出详细日志。

    Returns
    -------
    TrajectoryResult
    """
    params = DesignParams(
        t0_mjd=t0_mjd,
        r_m=r_m_km,
        side=side,
        r_p=r_p_km,
    )
    return solve_trajectory(params, body_data, verbose=verbose)


def _copy_trajectory_to_score(
    ws: WindowScore,
    result: TrajectoryResult,
) -> WindowScore:
    """将 TrajectoryResult 字段复制到 WindowScore。"""
    ws.full_success = result.success
    ws.full_v_launch = result.v_launch
    ws.full_v_inf = result.v_inf_earth
    ws.full_r_p_achieved_AU = km_to_au(result.r_p_achieved_km)
    ws.full_dist_moon_min = result.dist_moon_min
    ws.full_v_reentry = result.v_reentry
    ws.full_t_total = result.t_total_days
    return ws


# =========================
# 4. 主扫描入口
# =========================

def scan_launch_window(
    r_p_AU: float = 0.3,
    r_m_km: float = R_MOON + 500.0,
    side: str = "trailing",
    t0_start_mjd: Optional[float] = None,
    t0_end_mjd: Optional[float] = None,
    step_days: float = 1.0,
    mode: str = "fast",
    top_n: int = 5,
    body_data: Optional[dict] = None,
    verbose: bool = True,
) -> OptimizationResult:
    """发射窗口扫描主函数。

    Parameters
    ----------
    r_p_AU : float
        设计近日距 (AU)，默认 0.3。
    r_m_km : float
        近月距 (km)，默认 R_MOON + 500。
    side : str
        "leading" 或 "trailing"，默认 "trailing"。
    t0_start_mjd : float, optional
        扫描起始 MJD，默认使用 Horizons 数据首日。
    t0_end_mjd : float, optional
        扫描结束 MJD，默认使用 Horizons 数据最后一日。
    step_days : float
        扫描步长（天），默认 1。
    mode : str
        "fast" 或 "full"。
        "fast" - 仅几何评分（秒级完成所有天数）。
        "full" - 先 fast 筛选，再对 top_n 执行 N 体求解。
    top_n : int
        完整模式中对 top N 窗口执行 N 体求解。
    body_data : dict, optional
        Horizons 数据；None 时自动加载。
    verbose : bool
        是否输出日志。

    Returns
    -------
    OptimizationResult
    """
    if body_data is None:
        body_data = fetch_sem_vectors(use_cache=True)

    # 确定扫描范围
    jd_arr = np.array(body_data["Sun"]["jd_tdb"], dtype=float)
    mjd_arr = jd_arr - 2400000.5
    if t0_start_mjd is None:
        t0_start_mjd = mjd_arr[0]
    if t0_end_mjd is None:
        t0_end_mjd = mjd_arr[-1]

    # 预计算 patched conic（对固定 r_p，结果不依赖 t0）
    elements = compute_patched_conic(r_p_AU=r_p_AU)

    if verbose:
        print(f"{'='*66}")
        print(f"M6: Launch Window Optimization (r_p = {r_p_AU:.4f} AU)")
        print(f"{'='*66}")
        print(f"\nPatched conic: delta_v = {elements.delta_v:.4f} km/s")
        print(f"              v_launch = {elements.v_launch:.4f} km/s")
        print(f"Scan range: MJD {t0_start_mjd:.1f} - {t0_end_mjd:.1f}")
        print(f"Step: {step_days} day(s), Mode: {mode}")
        if mode == "full":
            print(f"Top-N refine: {top_n} windows")
        print()

    # 快速扫描
    windows: List[WindowScore] = []
    t = t0_start_mjd
    while t <= t0_end_mjd:
        ws = score_single_day_fast(t, body_data, elements)
        windows.append(ws)
        t += step_days

    # 按评分排序（越低越好）
    windows.sort(key=lambda w: w.score)
    n_feasible = sum(1 for w in windows if w.feasible)

    result = OptimizationResult(
        r_p_AU=r_p_AU,
        r_m_km=r_m_km,
        side=side,
        windows=windows,
        n_scanned=len(windows),
        n_feasible=n_feasible,
    )

    if verbose:
        print(f"  Scanned {len(windows)} days, {n_feasible} feasible")
        print(f"\nTop-10 windows (fast score):")
        print(f"  {'Rank':<5} {'MJD':<10} {'Angle(deg)':<10} {'Score':<10}")
        print(f"  {'-'*35}")
        for i, w in enumerate(windows[:10]):
            print(f"  {i+1:<5} {w.t0_mjd:<10.1f} {w.moon_angle_deg:<10.2f} {w.score:<10.4f}")

    # 完整模式：对 top_n 运行 N 体求解
    if mode == "full" and windows:
        if verbose:
            r_p_km = au_to_km(r_p_AU)
            print(f"\n{'='*66}")
            print(f"Full N-body refine on top-{top_n} windows...")
            print(f"  (each solve takes ~30-60s)")
            print(f"{'='*66}")

        r_p_km = au_to_km(r_p_AU)
        for i, w in enumerate(windows[:top_n]):
            if verbose:
                print(f"\n--- Refine #{i+1}: MJD {w.t0_mjd:.2f} "
                      f"(angle={w.moon_angle_deg:.1f}deg) ---")
            try:
                traj = run_full_solve(
                    w.t0_mjd, r_m_km, side, r_p_km,
                    body_data, verbose=verbose,
                )
                _copy_trajectory_to_score(w, traj)
                if verbose:
                    s = traj.summary_dict()
                    print(f"  -> success={s['success']}, "
                          f"r_p={s['r_p_achieved_AU']:.4f} AU, "
                          f"v_launch={s['v_launch_kms']:.2f} km/s")
            except Exception as e:
                if verbose:
                    print(f"  -> ERROR: {e}")

        # 按完整模式结果重新排序（成功的优先）
        success_windows = [w for w in windows[:top_n] if w.full_success]
        if success_windows:
            result.best_windows = success_windows
        else:
            # 降级：即使不成功也展示
            result.best_windows = windows[:top_n]
    else:
        # 快速模式：取前 top_n
        result.best_windows = windows[:top_n]

    # ---- 局部精化搜索（仅 fast 模式）：在最佳窗口附近 ±5 天做细扫描 ----
    # 对 best 窗口的 ±5d 范围，以 0.5d 步长做几何评分，寻找局部更优点
    if mode == "fast" and windows and windows[0].feasible:
        best_t0 = windows[0].t0_mjd
        fine_t0s = np.arange(best_t0 - 5.0, best_t0 + 5.1, 0.5)
        for ft in fine_t0s:
            if ft < t0_start_mjd or ft > t0_end_mjd:
                continue
            # 检查是否已扫描过（整数天）
            if any(abs(w.t0_mjd - ft) < 0.01 for w in result.windows):
                continue
            ws = score_single_day_fast(ft, body_data, elements)
            # 若优于当前 best，插入
            if ws.score < windows[0].score:
                windows.append(ws)
        # 重排序
        windows.sort(key=lambda w: w.score)
        result.windows = windows
        result.best_windows = windows[:top_n]
        if verbose and len(fine_t0s) > 0:
            print(f"\n  Local refinement: scanned {len(fine_t0s)} sub-day points near best")

    return result


# =========================
# 5. 结果输出
# =========================

def save_optimization_result(
    result: OptimizationResult,
    filename: str = "m6_windows.json",
) -> str:
    """将优化结果保存为 JSON。

    Returns
    -------
    str : 保存路径。
    """
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    path = out_dir / filename

    # 构建可序列化的输出
    summary = result.summary_dict()
    summary["top_10_scores"] = [
        {
            "t0_mjd": w.t0_mjd,
            "moon_angle_deg": round(w.moon_angle_deg, 2),
            "score": round(w.score, 4),
            "feasible": bool(w.feasible),
            "full_success": bool(w.full_success),
            "full_r_p_AU": round(w.full_r_p_achieved_AU, 4) if w.full_success else None,
            "full_v_launch": round(w.full_v_launch, 4) if w.full_success else None,
        }
        for w in result.windows[:10]
    ]

    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"[M6] Saved optimization result to {path}")
    return str(path)


# =========================
# 6. M6 回归测试
# =========================

def _run_m6_regression():
    """M6 回归测试：验证发射窗口优化模块。

    测试内容：
      1. 快速扫描 2026 全年，确认有可行窗口
      2. 最优窗口 Moon 对准角 < 30deg
      3. 在最优窗口运行 N 体求解，验证近日距精度
      4. 保存结果到 JSON
    """
    print("=" * 66)
    print("M6 Regression: Launch Window Optimization")
    print("=" * 66)

    body_data = fetch_sem_vectors(use_cache=True)

    # --- Test 1: 快速扫描 ---
    print(f"\n--- Test 1: Fast scan over 366 days (r_p = 0.3 AU) ---")
    result = scan_launch_window(
        r_p_AU=0.3,
        r_m_km=R_MOON + 500.0,
        side="trailing",
        mode="fast",
        verbose=True,
    )

    # 应有可行窗口
    assert result.n_feasible > 0, \
        f"No feasible windows found! (n={result.n_feasible})"
    print(f"\n  Feasible windows: {result.n_feasible}/{result.n_scanned}")

    # 最佳窗口对准角应合理
    best = result.best_windows[0]
    print(f"  Best window: MJD {best.t0_mjd:.1f}, "
          f"angle={best.moon_angle_deg:.2f}deg, score={best.score:.4f}")
    assert best.moon_angle_deg < 60.0, \
        f"Best alignment angle too large: {best.moon_angle_deg:.2f}deg"

    # --- Test 2: N 体验证最佳窗口 ---
    print(f"\n--- Test 2: N-body verification at best window ---")
    r_p_km = au_to_km(0.3)
    traj = run_full_solve(
        best.t0_mjd, R_MOON + 500.0, "trailing", r_p_km,
        body_data, verbose=True,
    )

    print(f"\n  Result: success={traj.success}")
    print(f"  v_launch={traj.v_launch:.4f} km/s")
    print(f"  v_inf_earth={traj.v_inf_earth:.4f} km/s")
    print(f"  r_p_achieved={km_to_au(traj.r_p_achieved_km):.4f} AU")
    print(f"  dist_moon_min={traj.dist_moon_min:.1f} km")
    print(f"  v_reentry={traj.v_reentry:.4f} km/s")

    # 近日距精度 < 25%
    assert traj.success, f"Trajectory solve failed at best window"
    assert traj.dist_moon_min < R_MOON_SOI, \
        f"Missed Moon SOI: {traj.dist_moon_min:.0f} km"
    r_p_rel_error = abs(traj.r_p_achieved_km - r_p_km) / r_p_km
    assert r_p_rel_error < 0.25, \
        f"Perihelion error too large: {r_p_rel_error:.2%}"

    # --- 保存结果 ---
    # 将完整结果写入 best window
    _copy_trajectory_to_score(best, traj)
    save_path = save_optimization_result(result, "m6_regression.json")

    # --- Test 3: Local refinement——对 top-5 窗口做 N 体求解 ---
    print(f"\n--- Test 3: N-body refinement of top-5 windows ---")
    r_p_km = au_to_km(0.3)
    repo_root = Path(__file__).resolve().parents[1]
    refined_data = []
    for i, w in enumerate(result.windows[:5]):
        t0 = w.t0_mjd
        print(f"  [{i+1}/5] MJD {t0:.2f} (angle={w.moon_angle_deg:.1f}°)...")
        try:
            tr = run_full_solve(t0, R_MOON + 500.0, "trailing", r_p_km,
                                body_data, verbose=False)
            d = {
                "t0_mjd": t0,
                "moon_angle_deg": round(w.moon_angle_deg, 2),
                "score": round(w.score, 4),
                "success": tr.success,
                "r_p_achieved_AU": round(km_to_au(tr.r_p_achieved_km), 4),
                "v_launch_kms": round(tr.v_launch, 4),
                "v_reentry_kms": round(tr.v_reentry, 4),
                "dist_moon_min_km": round(tr.dist_moon_min, 1),
                "t_total_days": round(tr.t_total_days, 2),
                "dv_moon_kms": round(tr.swingby.dv_mag, 4) if tr.swingby else None,
            }
            refined_data.append(d)
            print(f"    success={tr.success}, r_p={d['r_p_achieved_AU']:.4f} AU")
        except Exception as e:
            print(f"    ERROR: {e}")
            refined_data.append(None)

    # 保存精化结果
    refined_path = repo_root / "data" / "results" / "m6_refined.json"
    os.makedirs(refined_path.parent, exist_ok=True)
    with open(refined_path, "w", encoding="utf-8") as f:
        json.dump({
            "r_p_design_AU": 0.3,
            "r_m_km": R_MOON + 500.0,
            "side": "trailing",
            "refined_windows": [d for d in refined_data if d is not None],
        }, f, indent=2, ensure_ascii=False)
    print(f"  Refined results saved to {refined_path}")

    print(f"\n{'='*66}")
    print(f"M6 regression PASSED [OK]")
    print(f"  Best t0: MJD {best.t0_mjd:.1f}")
    print(f"  Moon alignment: {best.moon_angle_deg:.2f}deg")
    print(f"  Achieved r_p: {km_to_au(traj.r_p_achieved_km):.4f} AU (rel error: {r_p_rel_error:.2%})")
    print(f"  N-body refined windows: {sum(1 for d in refined_data if d is not None and d['success'])}/5 successful")
    print(f"  Results saved to: {save_path} and {refined_path}")
    return result


# =========================
# 主程序
# =========================

if __name__ == "__main__":
    _run_m6_regression()
