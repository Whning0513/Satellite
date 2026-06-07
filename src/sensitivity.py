"""
sensitivity.py
===============
M7: 灵敏度分析 (Sensitivity Analysis).

目的：
  评估轨迹对发射参数扰动的敏感性，确定关键控制参数。

方法：
  1. 蒙特卡洛方法：对 t0, r_m, side, C3 施加随机扰动，
     统计对近日距和再入速度的影响。
  2. 单参数扫描：逐个扰动关键参数，观察轨迹变化。

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
    R_EARTH, R_MOON, R_MOON_SOI,
    V_ESCAPE_EARTH,
    R_M_MIN, R_M_MAX, DT_MAIN,
)
from units import km_to_au, au_to_km, day_to_sec, sec_to_day, rad_to_deg
from trajectory import DesignParams, solve_trajectory, interpolate_state_at_mjd
from patched_conic import compute_patched_conic
from horizons import fetch_sem_vectors


# =========================
# 1. 灵敏度数据结构
# =========================

@dataclass
class SensitivityPoint:
    """单次灵敏度测试结果。"""
    label: str                     # 扰动参数名
    perturbation: float            # 扰动值（绝对/相对）
    perturbed_value: float         # 扰动后的参数值

    # 轨迹输出
    r_p_achieved_AU: float = 0.0
    v_launch_kms: float = 0.0
    v_reentry_kms: float = 0.0
    dist_moon_min_km: float = 0.0
    t_total_days: float = 0.0
    success: bool = False

    # 偏差（相对标称值）
    delta_r_p_AU: float = 0.0
    delta_v_launch: float = 0.0
    delta_v_reentry: float = 0.0


@dataclass
class SensitivityResult:
    """灵敏度分析结果。"""
    nominal_r_p_AU: float
    nominal_t0_mjd: float
    nominal_r_m_km: float
    nominal_side: str

    # 标称轨迹
    nominal_success: bool = False
    nominal_v_launch: float = 0.0
    nominal_v_reentry: float = 0.0
    nominal_r_p_achieved: float = 0.0

    # 扰动结果
    points: List[SensitivityPoint] = field(default_factory=list)

    # 灵敏度系数
    sensitivity: dict = field(default_factory=dict)

    def summary_dict(self) -> dict:
        d = {
            "nominal": {
                "t0_mjd": self.nominal_t0_mjd,
                "r_m_km": self.nominal_r_m_km,
                "side": self.nominal_side,
                "r_p_AU": self.nominal_r_p_AU,
                "success": self.nominal_success,
                "v_launch_kms": round(self.nominal_v_launch, 4),
                "v_reentry_kms": round(self.nominal_v_reentry, 4),
                "r_p_achieved_AU": round(self.nominal_r_p_achieved, 4),
            },
            "sensitivity": self.sensitivity,
        }
        return d


# =========================
# 2. 单参数扰动扫描
# =========================

def sweep_parameter(
    param_name: str,
    base_value: float,
    perturbations: List[float],
    base_params: DesignParams,
    body_data: dict,
    verbose: bool = True,
) -> List[SensitivityPoint]:
    """对单个参数施加扰动列表，运行轨迹求解。

    Parameters
    ----------
    param_name : str
        参数名称（用于标签）。
    base_value : float
        标称值。
    perturbations : List[float]
        扰动值列表（绝对值）。
    base_params : DesignParams
        基础设计参数。
    body_data : dict
        Horizons 数据。
    verbose : bool
        是否输出日志。

    Returns
    -------
    List[SensitivityPoint]
    """
    points = []
    for pert in perturbations:
        # 计算扰动后的参数值
        perturbed = base_value + pert

        # 根据参数类型修改 DesignParams
        p = DesignParams(
            t0_mjd=base_params.t0_mjd,
            r_m=base_params.r_m,
            side=base_params.side,
            r_p=base_params.r_p,
        )
        if param_name == "t0_mjd":
            p.t0_mjd = perturbed
        elif param_name == "r_m":
            p.r_m = max(R_MOON + 100.0, perturbed)
        elif param_name == "r_p":
            p.r_p = max(2.0 * 696340.0, perturbed)  # >= 2*R_SUN
        else:
            raise ValueError(f"Unknown parameter: {param_name}")

        label = f"{param_name}_pert={pert:+.2e}"

        try:
            traj = solve_trajectory(p, body_data, verbose=False)
            r_p_AU = km_to_au(traj.r_p_achieved_km) if np.isfinite(traj.r_p_achieved_km) else 0.0
            point = SensitivityPoint(
                label=label,
                perturbation=pert,
                perturbed_value=perturbed,
                r_p_achieved_AU=r_p_AU,
                v_launch_kms=traj.v_launch,
                v_reentry_kms=traj.v_reentry,
                dist_moon_min_km=traj.dist_moon_min,
                t_total_days=traj.t_total_days,
                success=traj.success,
            )
        except Exception as e:
            if verbose:
                print(f"  {label}: FAILED - {e}")
            point = SensitivityPoint(
                label=label,
                perturbation=pert,
                perturbed_value=perturbed,
                success=False,
            )
        points.append(point)

    return points


# =========================
# 3. 蒙特卡洛分析
# =========================

def monte_carlo_analysis(
    base_params: DesignParams,
    body_data: dict,
    n_samples: int = 50,
    sigma_t0: float = 1.0,       # MJD 扰动 σ
    sigma_r_m: float = 500.0,    # 近月距扰动 σ (km)
    sigma_r_p: float = 0.01 * AU_KM,  # 近日距扰动 σ (0.01 AU)
    random_seed: int = 42,
    verbose: bool = True,
) -> List[SensitivityPoint]:
    """蒙特卡洛扰动分析。

    Parameters
    ----------
    base_params : DesignParams
        标称设计参数。
    body_data : dict
        Horizons 数据。
    n_samples : int
        采样数。
    sigma_t0, sigma_r_m, sigma_r_p : float
        各参数的高斯扰动标准差。
    random_seed : int
        随机种子。
    verbose : bool
        是否输出日志。

    Returns
    -------
    List[SensitivityPoint]
    """
    rng = np.random.default_rng(random_seed)

    points = []
    successes = 0

    if verbose:
        print(f"\nMonte Carlo: {n_samples} samples, seed={random_seed}")
        print(f"  sigma_t0 = {sigma_t0:.2f} days")
        print(f"  sigma_r_m = {sigma_r_m:.1f} km")
        print(f"  sigma_r_p = {km_to_au(sigma_r_p):.6f} AU")

    for i in range(n_samples):
        # 生成扰动
        d_t0 = rng.normal(0, sigma_t0)
        d_rm = rng.normal(0, sigma_r_m)
        d_rp = rng.normal(0, sigma_r_p)

        p = DesignParams(
            t0_mjd=base_params.t0_mjd + d_t0,
            r_m=max(R_MOON + 100.0, base_params.r_m + d_rm),
            side=base_params.side,
            r_p=max(2.0 * 696340.0, base_params.r_p + d_rp),
        )

        label = f"mc_{i:03d}"

        try:
            traj = solve_trajectory(p, body_data, verbose=False)
            r_p_AU = km_to_au(traj.r_p_achieved_km) if np.isfinite(traj.r_p_achieved_km) else 0.0
            point = SensitivityPoint(
                label=label,
                perturbation=0.0,  # N/A for MC
                perturbed_value=0.0,
                r_p_achieved_AU=r_p_AU,
                v_launch_kms=traj.v_launch,
                v_reentry_kms=traj.v_reentry,
                dist_moon_min_km=traj.dist_moon_min,
                t_total_days=traj.t_total_days,
                success=traj.success,
            )
            if traj.success:
                successes += 1
        except Exception as e:
            point = SensitivityPoint(
                label=label, perturbation=0.0,
                perturbed_value=0.0, success=False,
            )
        points.append(point)

    if verbose:
        print(f"  Success rate: {successes}/{n_samples} ({100*successes/n_samples:.1f}%)")

    return points


# =========================
# 4. 灵敏度系数计算
# =========================

def compute_sensitivity(points: List[SensitivityPoint]) -> dict:
    """从扰动扫描中提取灵敏度系数。

    对于每个参数，计算：
      S = (Δr_p / r_p_nominal) / (Δparam / param_nominal)
    即近日距的相对变化与参数相对变化之比。
    """
    # 此处简化为汇总统计
    success_points = [p for p in points if p.success]

    if not success_points:
        return {"error": "No successful points for sensitivity analysis"}

    r_p_values = np.array([p.r_p_achieved_AU for p in success_points])
    v_launch_values = np.array([p.v_launch_kms for p in success_points])
    v_reentry_values = np.array([p.v_reentry_kms for p in success_points])

    return {
        "r_p_AU": {
            "mean": float(np.mean(r_p_values)),
            "std": float(np.std(r_p_values)),
            "min": float(np.min(r_p_values)),
            "max": float(np.max(r_p_values)),
        },
        "v_launch_kms": {
            "mean": float(np.mean(v_launch_values)),
            "std": float(np.std(v_launch_values)),
        },
        "v_reentry_kms": {
            "mean": float(np.mean(v_reentry_values)),
            "std": float(np.std(v_reentry_values)),
        },
        "n_success": len(success_points),
    }


# =========================
# 5. M7 回归测试
# =========================

def _run_m7_regression():
    """M7 回归测试：灵敏度分析验证。

    测试内容：
      1. 单参数扰动（t0, r_m, r_p）
      2. 蒙特卡洛随机扰动
      3. 灵敏度系数统计
      4. 保存结果到 JSON
    """
    print("=" * 66)
    print("M7 Regression: Sensitivity Analysis")
    print("=" * 66)

    body_data = fetch_sem_vectors(use_cache=True)

    # 标称参数（使用 M5 有效的窗口）
    base_params = DesignParams(
        t0_mjd=61066.0,
        r_m=R_MOON + 500.0,
        side="trailing",
        r_p=0.3 * AU_KM,
    )

    # 先求解标称轨迹
    print(f"\n--- Nominal trajectory ---")
    nominal = solve_trajectory(base_params, body_data, verbose=True)
    nominal_r_p_AU = km_to_au(nominal.r_p_achieved_km)
    print(f"  Nominal r_p = {nominal_r_p_AU:.4f} AU, v_launch = {nominal.v_launch:.4f} km/s")

    assert nominal.success, "Nominal trajectory must succeed for sensitivity analysis"

    # --- 测试 1: t0 扰动 ---
    print(f"\n--- Test 1: t0 sensitivity (+/-3 days) ---")
    t0_perturbations = [-3.0, -1.0, -0.5, 0.5, 1.0, 3.0]
    t0_points = sweep_parameter("t0_mjd", base_params.t0_mjd, t0_perturbations, base_params, body_data)

    n_success_t0 = sum(1 for p in t0_points if p.success)
    print(f"  t0 sweeps: {n_success_t0}/{len(t0_points)} succeeded")

    # --- 测试 2: r_m 扰动 ---
    print(f"\n--- Test 2: r_m sensitivity (+/-2000 km) ---")
    rm_perturbations = [-2000.0, -1000.0, -500.0, 500.0, 1000.0, 2000.0]
    rm_points = sweep_parameter("r_m", base_params.r_m, rm_perturbations, base_params, body_data)

    n_success_rm = sum(1 for p in rm_points if p.success)
    print(f"  r_m sweeps: {n_success_rm}/{len(rm_points)} succeeded")

    # --- 测试 3: r_p 扰动 ---
    print(f"\n--- Test 3: r_p sensitivity (+/-0.01 AU) ---")
    rp_perturbations = [-0.01*AU_KM, -0.005*AU_KM, 0.005*AU_KM, 0.01*AU_KM]
    rp_points = sweep_parameter("r_p", base_params.r_p, rp_perturbations, base_params, body_data)

    n_success_rp = sum(1 for p in rp_points if p.success)
    print(f"  r_p sweeps: {n_success_rp}/{len(rp_points)} succeeded")

    # --- 测试 4: 蒙特卡洛小规模 ---
    print(f"\n--- Test 4: Monte Carlo (20 samples) ---")
    mc_points = monte_carlo_analysis(
        base_params, body_data,
        n_samples=20,
        sigma_t0=1.0,
        sigma_r_m=500.0,
        sigma_r_p=0.005 * AU_KM,
        verbose=True,
    )

    # --- 合成结果 ---
    all_points = t0_points + rm_points + rp_points + mc_points

    # 计算标称值的偏差
    for p in all_points:
        if p.success:
            p.delta_r_p_AU = abs(p.r_p_achieved_AU - nominal_r_p_AU)
            p.delta_v_launch = abs(p.v_launch_kms - nominal.v_launch) / nominal.v_launch if nominal.v_launch > 0 else 0
            p.delta_v_reentry = abs(p.v_reentry_kms - nominal.v_reentry) / nominal.v_reentry if nominal.v_reentry > 0 else 0

    # 统计
    sens = compute_sensitivity(all_points)

    result = SensitivityResult(
        nominal_r_p_AU=nominal_r_p_AU,
        nominal_t0_mjd=base_params.t0_mjd,
        nominal_r_m_km=base_params.r_m,
        nominal_side=base_params.side,
        nominal_success=nominal.success,
        nominal_v_launch=nominal.v_launch,
        nominal_v_reentry=nominal.v_reentry,
        nominal_r_p_achieved=nominal_r_p_AU,
        points=all_points,
        sensitivity=sens,
    )

    # 保存
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    out_path = out_dir / "m7_sensitivity.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result.summary_dict(), f, indent=2, ensure_ascii=False)
    print(f"\n[M7] Saved sensitivity results to {out_path}")

    # 验证
    print(f"\nSensitivity results:")
    print(f"  r_p (AU): mean={sens['r_p_AU']['mean']:.4f}, "
          f"std={sens['r_p_AU']['std']:.4f}")
    print(f"  v_launch (km/s): mean={sens['v_launch_kms']['mean']:.4f}, "
          f"std={sens['v_launch_kms']['std']:.4f}")
    print(f"  v_reentry (km/s): mean={sens['v_reentry_kms']['mean']:.4f}, "
          f"std={sens['v_reentry_kms']['std']:.4f}")

    # 至少有一个扰动扫描有成功结果
    assert n_success_t0 > 0, "No successful t0 perturbations"
    assert sens["n_success"] > 0, "No successful sensitivity points"

    print(f"\n{'='*66}")
    print(f"M7 regression PASSED [OK]")
    return result


# =========================
# 主程序
# =========================

if __name__ == "__main__":
    _run_m7_regression()
