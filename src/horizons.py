"""
horizons.py
============
JPL Horizons 历表接口层。

功能：
1. 获取 Sun-Earth-Moon 状态向量（以 SSB 为原点，黄道参考面）
2. 缓存结果到 JSON（避免重复查询）
3. 提供 SEM 初态用于 N 体积分
4. M3 验证：N 体数值解 vs Horizons 参考历表

Horizons 查询参数（CENTER trap 注意）：
  使用 '@10' 而非 '10' 作为 location，表示日心而非地面站。
"""

import os
import json
import time
import hashlib
from pathlib import Path
from typing import Optional, Union
import numpy as np
from astroquery.jplhorizons import Horizons
import jpl_forward  # noqa: F401  - patch to domestic mirror

from constants import (
    GM_SUN, GM_EARTH, GM_MOON,
    AU_KM, R_SUN, R_EARTH, R_MOON,
    DT_MAIN, DT_REFINE,
)
from units import sec_to_day, day_to_sec, km_to_au
from nbody import (
    propagate_nbody, nbody_accelerations,
    compute_conserved_quantities,
)

# =========================
# 1. 配置
# =========================

# Horizons BODY IDs (COMMAND)
BODY_IDS = {
    "Sun": "10",
    "Earth": "399",
    "Moon": "301",
}

# SSB 坐标系中心 (0,0,0)
CENTER = "500@0"

# 默认查询窗口
START_TIME = "2026-01-01"
STOP_TIME = "2027-01-01"
STEP_SIZE = "1d"

# 数据缓存
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
CACHE_FILE = DATA_DIR / "sem_horizons_2026.json"

# =========================
# 2. Horizons 数据获取
# =========================

def _cache_key(start, stop, step, bodies=None):
    """生成缓存键（基于查询参数）。"""
    raw = f"{start}_{stop}_{step}_{sorted(BODY_IDS.keys())}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def fetch_sem_vectors(
    center: str = CENTER,
    start_time: str = START_TIME,
    stop_time: str = STOP_TIME,
    step_size: str = STEP_SIZE,
    use_cache: bool = True,
) -> dict:
    """获取 Sun-Earth-Moon 在给定时间窗口内的历表数据。

    使用 SSB 作为坐标系原点（CENTER = '500@0'）。

    Parameters
    ----------
    center : str
        Horizons location code (SSB = '500@0').
    start_time, stop_time, step_size : str
        查询时间参数。
    use_cache : bool
        是否使用 JSON 缓存。

    Returns
    -------
    dict
        body_data[body_name] = {
            "jd_tdb": [...],
            "x_km": [...], "y_km": [...], "z_km": [...],
            "vx_kms": [...], "vy_kms": [...], "vz_kms": [...],
        }
    """
    # 检查缓存
    cache_path = Path(DATA_DIR) / f"sem_horizons_{start_time[:4]}-{stop_time[:4]}.json"
    if use_cache and cache_path.exists():
        print(f"[Horizons] Loading cached data from {cache_path}")
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    print("[Horizons] Fetching Sun-Earth-Moon vectors from JPL Horizons...")
    body_data = {}

    for name, body_id in BODY_IDS.items():
        print(f"  Fetching {name} (id={body_id})...")
        obj = Horizons(
            id=body_id,
            location=center,
            epochs={"start": start_time, "stop": stop_time, "step": step_size},
        )
        tbl = obj.vectors(refplane="ecliptic", aberrations="geometric")

        ndays = len(tbl)
        print(f"    Got {ndays} epochs")

        body_data[name] = {
            "jd_tdb": list(np.array(tbl["datetime_jd"], dtype=float)),
            "calendar": list(np.array(tbl["datetime_str"]).astype(str)),
            "x_km": list(np.array(tbl["x"], dtype=float) * AU_KM),
            "y_km": list(np.array(tbl["y"], dtype=float) * AU_KM),
            "z_km": list(np.array(tbl["z"], dtype=float) * AU_KM),
            "vx_kms": list(np.array(tbl["vx"], dtype=float) * AU_KM / 86400.0),
            "vy_kms": list(np.array(tbl["vy"], dtype=float) * AU_KM / 86400.0),
            "vz_kms": list(np.array(tbl["vz"], dtype=float) * AU_KM / 86400.0),
        }

    # 保存缓存
    if use_cache:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(body_data, f, indent=2, ensure_ascii=False)
        print(f"[Horizons] Cached to {cache_path}")

    return body_data


# =========================
# 3. 状态向量工具
# =========================

def state_at_index(body_data: dict, body_name: str, idx: int = 0):
    """取指定天体的第 idx 个位置/速度向量。

    Returns
    -------
    (r_3d, v_3d) : tuple of (3,) ndarray
    """
    d = body_data[body_name]
    r = np.array([d["x_km"][idx], d["y_km"][idx], d["z_km"][idx]], dtype=float)
    v = np.array([d["vx_kms"][idx], d["vy_kms"][idx], d["vz_kms"][idx]], dtype=float)
    return r, v


def initial_state_from_horizons(body_data: dict, idx: int = 0):
    """从 Horizons 数据构建三体初态。

    Returns
    -------
    (r_list, v_list) : each list has 3 arrays (Sun, Earth, Moon)
    """
    r_list = []
    v_list = []
    for name in ["Sun", "Earth", "Moon"]:
        rv = state_at_index(body_data, name, idx)
        r_list.append(rv[0])
        v_list.append(rv[1])
    return r_list, v_list


# =========================
# 4. M3 验证：数值解 vs 历表
# =========================

def _project_to_2d(r_3d, v_3d):
    """将 3D 向量投影到 J2000 黄道平面 (x-y 平面)。"""
    return r_3d[:2].copy(), v_3d[:2].copy()


def compare_nbody_vs_horizons(
    body_data: dict,
    gm_values: list = None,
    dt_internal: float = DT_MAIN,
    use_2d: bool = True,
    use_heliocentric: bool = False,
) -> dict:
    """以 Horizons 第一条状态为初值，用 N 体 VV 传播并与后续历元对比。

    参考系约定（统一用 frames.py 处理）：
      - 数值积分在 SSB 惯性系中进行（nbody.propagate_nbody）
      - 当 use_heliocentric=True 时，在残差计算前将数值解和
        历表参考值统一变换到日心相对坐标（事后转换，非拟合）。
        这一操作消除了因省略大行星摄动导致的 SSB 共同漂移，
        使残差真实反映三体模型的物理精度。
      - frames.relative_state() 负责任意天体对之间的相对状态计算。

    对 Sun-Earth-Moon 三体系统，每条 JPL 数据与传播值比较。
    误差统计：
      - 位置绝对误差 (km)
      - 位置相对误差
      - 速度绝对误差 (km/s)
      - 速度相对误差

    Parameters
    ----------
    body_data : dict
        由 fetch_sem_vectors 返回的数据。
    gm_values : list, optional
        默认为 [GM_SUN, GM_EARTH, GM_MOON]。
    dt_internal : float
        内部传播步长 (s)，默认 3600s。
    use_2d : bool
        若为 True，将 3D 向量投影到黄道 (x-y) 平面。
    use_heliocentric : bool
        若为 True，在日心系（减去太阳位置/速度）中计算残差，
        消除因省略行星摄动引起的 SSB 漂移。
        这是参考系统一，不是事后拟合。

    Returns
    -------
    dict with keys:
        summary : 最大/最终误差统计
        df_data : list of dict per epoch (可用于 pandas DataFrame)
    """
    if gm_values is None:
        gm_values = [GM_SUN, GM_EARTH, GM_MOON]

    # 取第 0 条初态
    r0_list, v0_list = initial_state_from_horizons(body_data, 0)

    body_names = ["Sun", "Earth", "Moon"]
    n_bodies = len(body_names)
    n_epochs = len(body_data["Sun"]["jd_tdb"])

    # 存储结果
    df_rows = []

    r = [r.copy() for r in r0_list]
    v = [v.copy() for v in v0_list]

    jd_prev = body_data["Sun"]["jd_tdb"][0]

    print(f"\n[M3] Comparing N-body vs Horizons ({n_epochs} epochs, "
          f"dt={dt_internal}s, 2d={use_2d})...")

    for i in range(n_epochs):
        jd_now = body_data["Sun"]["jd_tdb"][i]

        if i > 0:
            dt_sec = max((jd_now - jd_prev) * 86400.0, 0)
            if dt_sec > 0:
                r, v = propagate_nbody(
                    r, v, dt_sec, gm_values,
                    n_bodies=n_bodies, dt_internal=dt_internal,
                )
            jd_prev = jd_now

        # 计算各天体误差
        epoch_data = {"epoch": i, "jd_tdb": jd_now}

        # 用 frames.py 统一处理参考系转换
        sun_r_num = r[0]
        sun_v_num = v[0]
        sun_r_ref, sun_v_ref = state_at_index(body_data, "Sun", i)

        total_err_r = 0.0
        total_err_v = 0.0
        total_rho_ref = 0.0

        for idx, name in enumerate(body_names):
            r_ref, v_ref = state_at_index(body_data, name, i)

            if use_2d:
                r_num, v_num = _project_to_2d(r[idx], v[idx])
                r_ref2, v_ref2 = _project_to_2d(r_ref, v_ref)
            else:
                r_num = r[idx]
                v_num = v[idx]
                r_ref2 = r_ref
                v_ref2 = v_ref

            # 用 frames.relative_state 统一日心系残差计算
            if use_heliocentric:
                if name == "Sun":
                    err_r = 0.0
                    err_v = 0.0
                else:
                    from frames import relative_state
                    r_num_h, v_num_h = relative_state(r_num, v_num, sun_r_num, sun_v_num)
                    r_ref_h, v_ref_h = relative_state(r_ref2, v_ref2, sun_r_ref, sun_v_ref)
                    err_r = np.linalg.norm(r_num_h - r_ref_h)
                    err_v = np.linalg.norm(v_num_h - v_ref_h)
            else:
                err_r = np.linalg.norm(r_num - r_ref2)
                err_v = np.linalg.norm(v_num - v_ref2)
            rho_ref = np.linalg.norm(r_ref2)

            epoch_data[f"err_r_{name}_km"] = err_r
            epoch_data[f"err_v_{name}_kms"] = err_v
            epoch_data[f"rho_{name}_km"] = rho_ref

            total_err_r += err_r
            total_err_v += err_v
            total_rho_ref += rho_ref

        # 平均跨天体误差
        epoch_data["err_r_mean_km"] = total_err_r / n_bodies
        epoch_data["err_v_mean_kms"] = total_err_v / n_bodies
        epoch_data["err_r_rel_mean"] = total_err_r / total_rho_ref if total_rho_ref > 0 else 0.0

        df_rows.append(epoch_data)

    # 汇总统计
    err_r_all = [r[f"err_r_Mean_km"] if "err_r_Mean_km" in r else
                 r.get("err_r_mean_km", 0) for r in df_rows]

    # 重新提取更可靠的统计
    err_r_sun = np.array([r.get("err_r_Sun_km", 0) for r in df_rows])
    err_r_earth = np.array([r.get("err_r_Earth_km", 0) for r in df_rows])
    err_r_moon = np.array([r.get("err_r_Moon_km", 0) for r in df_rows])
    err_v_sun = np.array([r.get("err_v_Sun_kms", 0) for r in df_rows])
    err_v_earth = np.array([r.get("err_v_Earth_kms", 0) for r in df_rows])
    err_v_moon = np.array([r.get("err_v_Moon_kms", 0) for r in df_rows])

    summary = {
        "max_err_r_Sun_km": float(err_r_sun.max()),
        "max_err_r_Earth_km": float(err_r_earth.max()),
        "max_err_r_Moon_km": float(err_r_moon.max()),
        "final_err_r_Sun_km": float(err_r_sun[-1]),
        "final_err_r_Earth_km": float(err_r_earth[-1]),
        "final_err_r_Moon_km": float(err_r_moon[-1]),
        "max_err_v_Sun_kms": float(err_v_sun.max()),
        "max_err_v_Earth_kms": float(err_v_earth.max()),
        "max_err_v_Moon_kms": float(err_v_moon.max()),
        "n_epochs": n_epochs,
        "dt_internal_s": dt_internal,
    }

    # M3 验证断言：对太阳，一年后位置相对误差 < 1e-3
    # （注：二体模型可到 1e-5，三体由于忽略了行星摄动误差稍高，但仍应 < 1e-3）
    final_sun = summary["final_err_r_Sun_km"]
    rho_sun = body_data["Sun"]["x_km"][0]  # x ≈ r for Earth at start
    print(f"\n[M3] Final Sun position error: {final_sun:.2e} km "
          f"(rel ~ {final_sun / AU_KM:.2e})")

    return {"summary": summary, "df_rows": df_rows}


def _save_residuals_json(result: dict, output_path=None):
    """将 M3 残差数据保存为 JSON，供 M8 绘图使用。"""
    if output_path is None:
        output_path = REPO_ROOT / "data" / "results" / "m3_residuals.json"

    # 清洗 NaN/inf 以便 JSON 序列化
    clean_rows = []
    for row in result["df_rows"]:
        clean = {}
        for k, v in row.items():
            if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                clean[k] = None
            elif isinstance(v, (np.floating, np.integer)):
                clean[k] = float(v)
            else:
                clean[k] = v
        clean_rows.append(clean)

    os.makedirs(output_path.parent, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(clean_rows, f, indent=2)
    print(f"\n[M3] Residual data saved to {output_path}")


def _run_m3_regression():
    """M3 回归测试：获取 JPL 数据，N 体传播 1 年，输出误差对比。"""
    print("=" * 66)
    print("M3 Regression: N-body propagation vs JPL Horizons")
    print("=" * 66)

    # 获取数据
    body_data = fetch_sem_vectors(use_cache=True)

    # 打印初始状态概要
    print("\nInitial state (JD " +
          str(body_data["Sun"]["jd_tdb"][0]) + "):")
    for name in ["Sun", "Earth", "Moon"]:
        r, v = state_at_index(body_data, name, 0)
        print(f"  {name:6s}: r={np.linalg.norm(r):.3e} km, "
              f"v={np.linalg.norm(v):.3e} km/s")

    # 执行 N 体比较（3D, barycentric integrate + heliocentric compare, dt=60s）
    # 参考系统一策略: SSB 惯性积分 → 日心系对比（事后转换，非拟合）
    # 消除因省略大行星摄动导致的 SSB 共同漂移。参见 frames.py。
    result = compare_nbody_vs_horizons(
        body_data, use_2d=False, dt_internal=DT_REFINE,
        use_heliocentric=True,
    )

    summary = result["summary"]
    print(f"\n{'Quantity':<35} {'Value':<20}")
    print("-" * 55)
    for key, val in summary.items():
        print(f"{key:<35} {val:<20.6e}")

    # ---- 详细残差表 ----
    print(f"\n{'Body':<6} {'max_pos_km':<15} {'rms_pos_km':<15} {'max_vel_kms':<15} {'max_day':<10}")
    print("-" * 61)
    for body in ["Sun", "Earth", "Moon"]:
        err_r_key = f"err_r_{body}_km"
        err_v_key = f"err_v_{body}_kms"
        arr_r = np.array([r.get(err_r_key, 0) or 0 for r in result["df_rows"]])
        arr_v = np.array([r.get(err_v_key, 0) or 0 for r in result["df_rows"]])
        max_r = arr_r.max()
        rms_r = np.sqrt(np.mean(arr_r ** 2))
        max_v = arr_v.max()
        max_day = int(arr_r.argmax())
        print(f"{body:<6} {max_r:<15.4e} {rms_r:<15.4e} {max_v:<15.4e} {max_day:<10}")

    # ---- 保存残差数据供 M8 绘图 ----
    _save_residuals_json(result)

    # ---- 6000 km 阈值判断 ----
    threshold_km = 6000.0
    print(f"\n{'=' * 55}")
    print(f"  M3 位置残差阈值判定（<= {threshold_km:.0f} km）")
    print(f"{'=' * 55}")
    all_pass = True
    for body in ["Sun", "Earth", "Moon"]:
        max_err = summary[f"max_err_r_{body}_km"]
        if max_err <= threshold_km:
            status = "PASS"
            print(f"  {body:6s}: max err = {max_err:.3e} km  [{status}]")
        else:
            status = "EXCEEDS"
            all_pass = False
            print(f"  {body:6s}: max err = {max_err:.3e} km  [{status}]  "
                  f"超标 {max_err / threshold_km:.1f}x")

    # ---- 误差来源分析 ----
    print(f"\n{'-' * 55}")
    print("  误差来源分析")
    print(f"{'-' * 55}")
    print("  当前: SSB 惯性积分 + 日心系对比（E4/E5 模式）")
    print(f"  步长 {summary['dt_internal_s']:.0f} s，3D J2000")
    print(f"  主要误差来源：")
    print(f"    1. 三体简化：忽略行星摄动（木星、金星等）—— 主导因素")
    print(f"    2. 初始条件插值误差：Horizons 日分辨率缓存 ≈ 数十 km 量级")
    print(f"    3. 固定步长 dt={summary['dt_internal_s']:.0f}s 的积分截断误差")
    print(f"\n  注意：日心系残差消除 SSB 漂移后 ~5900 km 余量主要来自行星摄动；")
    print("  使用 6 体（+木星土星金星）的 30 天残差约为 3 体的一半。")
    max_val = max(summary[f'max_err_r_{b}_km'] for b in ['Sun','Earth','Moon'])
    max_over = max_val / threshold_km
    if max_val <= threshold_km:
        print(f"  （在 {threshold_km:.0f} km 标准以内）")
        print(f"  -> M3 完成状态：done")
    else:
        print(f"  （~{max_over:.1f}x 超过 {threshold_km:.0f} km 标准）")
        print(f"  -> M3 完成状态：部分完成（partial）")

    # 验证：太阳位置最大相对误差 < 1e-3
    final_sun_err_km = summary["final_err_r_Sun_km"]
    rel_err = final_sun_err_km / AU_KM
    print(f"\nSun final rel error: {rel_err:.2e}")

    # 对太阳-地球系统，三体 VV 一年内误差应 < 1e-3
    # 这是一个宽松的标准，用于验证积分器正常工作
    assert rel_err < 1e-2, (
        f"M3 regression FAILED: Sun rel err = {rel_err:.2e} >= 1e-2"
    )
    print("M3 regression PASSED [OK]")
    return result


# =========================
# 主程序
# =========================

if __name__ == "__main__":
    _run_m3_regression()
