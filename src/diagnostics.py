"""
diagnostics.py
==============
M3 诊断模块：时间和单位验证。

验证 Horizons 数据的单位、日期步长、参考值确保测试环境可靠。
"""

import json
import os
import numpy as np
from pathlib import Path

from constants import AU_KM
from units import km_to_au


def check_horizons_units(body_data: dict) -> dict:
    """验证 Horizons 返回数据的单位转换正确性。

    检查：
    1. 2026-06-15 Earth 日心距离 ≈ 1.015 AU
    2. Earth 日心速度 ≈ 29.13 km/s
    3. 数据点时间步长是否 ≈ 86400s

    Returns
    -------
    dict : 检查结果
    """
    results = {}

    # 定位 2026-06-15 附近的索引
    jd_arr = np.array(body_data["Sun"]["jd_tdb"], dtype=float)
    # 2026-06-15 ≈ JD 2460806.5
    jd_target = 2460806.5
    idx = np.argmin(np.abs(jd_arr - jd_target))

    # Earth 日心状态
    r_e = np.array([
        body_data["Earth"]["x_km"][idx],
        body_data["Earth"]["y_km"][idx],
        body_data["Earth"]["z_km"][idx],
    ], dtype=float)
    v_e = np.array([
        body_data["Earth"]["vx_kms"][idx],
        body_data["Earth"]["vy_kms"][idx],
        body_data["Earth"]["vz_kms"][idx],
    ], dtype=float)

    r_e_au = km_to_au(np.linalg.norm(r_e))
    v_e_kms = np.linalg.norm(v_e)

    results["earth_r_AU_2026_06_15"] = float(round(r_e_au, 6))
    results["earth_v_kms_2026_06_15"] = float(round(v_e_kms, 4))
    results["earth_r_sanity"] = "PASS" if 0.9 < r_e_au < 1.1 else "FAIL"
    results["earth_v_sanity"] = "PASS" if 25 < v_e_kms < 35 else "FAIL"

    # 检查时间步长
    jd_diffs = np.diff(jd_arr)
    avg_jd_step = float(np.mean(jd_diffs))
    avg_sec_step = avg_jd_step * 86400.0
    results["avg_jd_step"] = avg_jd_step
    results["avg_sec_step"] = avg_sec_step
    results["expected_step_86400s"] = abs(avg_sec_step - 86400.0) < 10.0

    # 检查 JD → 年映射
    jd_start = jd_arr[0]
    jd_end = jd_arr[-1]
    year_start = 2000 + (jd_start - 2451545.0) / 365.25
    year_end = 2000 + (jd_end - 2451545.0) / 365.25
    results["jd_start"] = float(jd_start)
    results["jd_end"] = float(jd_end)
    results["year_frac_start"] = float(round(year_start, 3))
    results["year_frac_end"] = float(round(year_end, 3))
    results["n_epochs"] = len(jd_arr)
    results["time_range_sanity"] = "PASS" if 2025 < year_start < 2028 else "FAIL"

    # Sun 位置检查（SSB 原点应为 0 附近）
    r_sun = np.array([
        body_data["Sun"]["x_km"][0],
        body_data["Sun"]["y_km"][0],
        body_data["Sun"]["z_km"][0],
    ], dtype=float)
    sun_dist = np.linalg.norm(r_sun)
    results["sun_dist_SSB_km"] = float(round(sun_dist, 1))
    # Sun 在 SSB 原点附近（~几百万 km 量级，因为太阳本身绕 SSB 运动）
    results["sun_near_barycenter"] = "PASS" if sun_dist < 2e6 else "FAIL"

    # AU 单位检查
    r_e_direct_au = np.sqrt(
        float(body_data["Earth"]["x_km"][idx]) ** 2
        + float(body_data["Earth"]["y_km"][idx]) ** 2
        + float(body_data["Earth"]["z_km"][idx]) ** 2
    ) / AU_KM
    results["earth_r_au_direct_kms_conversion"] = float(round(r_e_direct_au, 6))
    results["au_km_value"] = AU_KM

    return results


def run_horizons_sanity_check(body_data: dict = None) -> dict:
    """执行全部 Horizons 数据诊断检查。"""
    if body_data is None:
        from horizons import fetch_sem_vectors
        body_data = fetch_sem_vectors(use_cache=True)

    result = check_horizons_units(body_data)

    print("=" * 66)
    print("Diagnostics: Horizons Data Sanity Check")
    print("=" * 66)
    print(f"  Earth r (2026-06-15): {result.get('earth_r_AU_2026_06_15', 'N/A'):>8} AU")
    print(f"  Earth v (2026-06-15): {result.get('earth_v_kms_2026_06_15', 'N/A'):>8} km/s")
    print(f"  Earth r sanity:  {result.get('earth_r_sanity', 'N/A')}")
    print(f"  Earth v sanity:  {result.get('earth_v_sanity', 'N/A')}")
    print(f"  Avg JD step:     {result.get('avg_jd_step', 'N/A'):.6f} days")
    print(f"  Avg step (s):    {result.get('avg_sec_step', 'N/A'):.1f} s")
    print(f"  Expected 86400s: {result.get('expected_step_86400s', 'N/A')}")
    print(f"  JD range:        {result.get('jd_start', 'N/A'):.1f} - {result.get('jd_end', 'N/A'):.1f}")
    print(f"  Year range:      {result.get('year_frac_start', 'N/A')} - {result.get('year_frac_end', 'N/A')}")
    print(f"  Sun dist SSB:    {result.get('sun_dist_SSB_km', 'N/A'):.3e} km")
    print(f"  AU_KM:           {result.get('au_km_value', 'N/A')}")
    print(f"  N epochs:        {result.get('n_epochs', 'N/A')}")

    # 保存诊断
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)
    out_path = out_dir / "m3_time_unit_check.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"\n[Diagnostics] Saved to {out_path}")

    return result


if __name__ == "__main__":
    run_horizons_sanity_check()
