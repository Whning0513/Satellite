"""
m3_residual_ablation.py
========================
M3 残差消融实验：系统地比较多种参考系、维度、步长组合，
找到真正误差最低的模式并保留改进链路。

实验列表:
  E0: 2D SSB inertial, dt=3600s                (原始基线)
  E1: 3D SSB inertial, dt=3600s                (维度扩展)
  E2: 3D SSB inertial, dt=900s                 (步长细化)
  E3: 3D SSB propagate + heliocentric compare, dt=900s  (参考系归一)
  E4: 3D SSB propagate + heliocentric compare, dt=60s   (参考系归一 + 精步长)
  E5: 3D SSB propagate + heliocentric compare, dt=300s  (额外精化)
  E6: 3D heliocentric relative integration, dt=900s     (日心相对动力学)

输出:
  data/results/m3_residual_ablation.json
  data/results/m3_residual_ablation.csv
"""

import json
import os
import csv
import sys
import time
import numpy as np
from pathlib import Path
from typing import List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from constants import GM_SUN, GM_EARTH, GM_MOON, AU_KM
from frames import to_heliocentric, project_to_2d, BODY_NAMES_DEFAULT
from nbody import propagate_nbody as barycentric_propagate
from dynamics import propagate_nbody as flexible_propagate


ABLATION_EXPERIMENTS = [
    {"name": "E0", "dim": 2, "dt_s": 3600.0,
     "integration": "barycentric", "comparison": "barycentric"},
    {"name": "E1", "dim": 3, "dt_s": 3600.0,
     "integration": "barycentric", "comparison": "barycentric"},
    {"name": "E2", "dim": 3, "dt_s": 900.0,
     "integration": "barycentric", "comparison": "barycentric"},
    {"name": "E3", "dim": 3, "dt_s": 900.0,
     "integration": "barycentric", "comparison": "heliocentric"},
    {"name": "E4", "dim": 3, "dt_s": 60.0,
     "integration": "barycentric", "comparison": "heliocentric"},
    {"name": "E5", "dim": 3, "dt_s": 300.0,
     "integration": "barycentric", "comparison": "heliocentric"},
    {"name": "E6", "dim": 3, "dt_s": 900.0,
     "integration": "heliocentric_relative", "comparison": "heliocentric"},
]


def _body_stats(err_r: np.ndarray, err_v: np.ndarray) -> dict:
    return {
        "max_pos_km": float(np.max(err_r)),
        "rms_pos_km": float(np.sqrt(np.mean(err_r ** 2))),
        "max_vel_kms": float(np.max(err_v)),
        "max_day": int(np.argmax(err_r)),
    }


def run_single_experiment(body_data, cfg, gm_values, n_bodies=3,
                          body_names=None) -> dict:
    if body_names is None:
        body_names = BODY_NAMES_DEFAULT

    from horizons import initial_state_from_horizons, state_at_index
    r0_all, v0_all = initial_state_from_horizons(body_data, 0)

    use_2d = cfg["dim"] == 2
    is_barycentric_int = cfg["integration"] == "barycentric"
    is_heliocentric_compare = cfg["comparison"] == "heliocentric"

    # ---- 初始化态 ----
    if is_barycentric_int:
        r0 = [ri.copy() for ri in r0_all]
        v0 = [vi.copy() for vi in v0_all]
        if use_2d:
            r0, v0 = project_to_2d(r0, v0)
        propagate_fn = lambda r, v, dt, gm, nb, dti: \
            barycentric_propagate(r, v, dt, gm, n_bodies=nb, dt_internal=dti)
    else:
        # heliocentric_relative integration
        r0, v0 = to_heliocentric(r0_all, v0_all, sun_idx=0)
        if use_2d:
            r0, v0 = project_to_2d(r0, v0)
        propagate_fn = lambda r, v, dt, gm, nb, dti: \
            flexible_propagate(r, v, dt, gm, n_bodies=nb, dt_internal=dti,
                               accel_mode="heliocentric_relative", sun_idx=0)

    dt_internal = cfg["dt_s"]
    n_epochs = len(body_data["Sun"]["jd_tdb"])
    jd_arr = np.array(body_data["Sun"]["jd_tdb"], dtype=float)

    # 预计算参考状态（始终同时计算 SSB 和日心系，避免分支错误）
    ref_ssb_list = []
    ref_helio_list = []
    for i in range(n_epochs):
        rr, vv = [], []
        for name in body_names:
            r_ref, v_ref = state_at_index(body_data, name, i)
            rr.append(r_ref)
            vv.append(v_ref)
        ref_ssb_list.append((rr, vv))
        rh, vh = to_heliocentric(rr, vv, sun_idx=0)
        ref_helio_list.append((rh, vh))

    # ---- 积分循环 ----
    r = [ri.copy() for ri in r0]
    v = [vi.copy() for vi in v0]
    jd_prev = jd_arr[0]
    err_arrays = {name: {"r": [], "v": []} for name in body_names}

    for i in range(n_epochs):
        jd_now = jd_arr[i]
        if i > 0:
            dt_sec = max((jd_now - jd_prev) * 86400.0, 0)
            if dt_sec > 0:
                r, v = propagate_fn(r, v, dt_sec, gm_values, n_bodies, dt_internal)
            jd_prev = jd_now

        for idx, name in enumerate(body_names):
            if is_heliocentric_compare and is_barycentric_int:
                # 方法：SSB 积分 → 日心系对比（事后转换）
                ref_ssb, vref_ssb = ref_ssb_list[i]
                r_sun_num = r[0]
                v_sun_num = v[0]
                r_sun_ref = ref_ssb[0]
                v_sun_ref = vref_ssb[0]
                if use_2d:
                    rn = r[idx][:2] - r_sun_num[:2]
                    rr = ref_ssb[idx][:2] - r_sun_ref[:2]
                    vn = v[idx][:2] - v_sun_num[:2]
                    vr = vref_ssb[idx][:2] - v_sun_ref[:2]
                else:
                    rn = r[idx] - r_sun_num
                    rr = ref_ssb[idx] - r_sun_ref
                    vn = v[idx] - v_sun_num
                    vr = vref_ssb[idx] - v_sun_ref
                err_r = np.linalg.norm(rn - rr)
                err_v = np.linalg.norm(vn - vr)
                err_arrays[name]["r"].append(err_r)
                err_arrays[name]["v"].append(err_v)

            elif not is_barycentric_int:
                # 方法：日心相对动力学积分 → 日心系对比
                # ref_helio_list[i] = (r_helio_list, v_helio_list), each list of length n_bodies
                rh_list, vh_list = ref_helio_list[i]
                if use_2d:
                    rn = r[idx][:2] if r[idx].ndim == 1 else r[idx]
                    rr = rh_list[idx][:2]
                    vn = v[idx][:2]
                    vr = vh_list[idx][:2]
                else:
                    rn = r[idx]
                    rr = rh_list[idx]
                    vn = v[idx]
                    vr = vh_list[idx]
                err_r = np.linalg.norm(rn - rr)
                err_v = np.linalg.norm(vn - vr)
                err_arrays[name]["r"].append(err_r)
                err_arrays[name]["v"].append(err_v)
            else:
                # 方法：SSB 积分 → SSB 系对比
                r_ref, v_ref = state_at_index(body_data, name, i)
                if use_2d:
                    rn = r[idx][:2]
                    vn = v[idx][:2]
                    rr = r_ref[:2]
                    vr = v_ref[:2]
                else:
                    rn = r[idx]
                    vn = v[idx]
                    rr = r_ref
                    vr = v_ref
                err_r = np.linalg.norm(rn - rr)
                err_v = np.linalg.norm(vn - vr)
                err_arrays[name]["r"].append(err_r)
                err_arrays[name]["v"].append(err_v)

    # ---- 汇总 ----
    body_stats = {}
    overall_max = 0.0
    for name in body_names:
        bs = _body_stats(np.array(err_arrays[name]["r"]),
                         np.array(err_arrays[name]["v"]))
        body_stats[name.lower()] = bs
        overall_max = max(overall_max, bs["max_pos_km"])

    is_heliocentric_int = not is_barycentric_int
    return {
        "experiment": cfg["name"],
        "integration": cfg["integration"],
        "comparison": cfg["comparison"],
        "dimension": f"{cfg['dim']}d",
        "dt_s": cfg["dt_s"],
        "body_stats": body_stats,
        "overall_max_pos_km": overall_max,
        "threshold_6000km": overall_max <= 6000.0,
    }


def run_ablation(experiments=None, verbose=True):
    if experiments is None:
        experiments = ABLATION_EXPERIMENTS

    from horizons import fetch_sem_vectors
    body_data = fetch_sem_vectors(use_cache=True)
    gm_values = [GM_SUN, GM_EARTH, GM_MOON]
    body_names = ["Sun", "Earth", "Moon"]
    results = []

    for cfg in experiments:
        if verbose:
            print(f"\n{'='*60}")
            print(f"  {cfg['name']}: integrate={cfg['integration']}, "
                  f"compare={cfg['comparison']}, {cfg['dim']}d, dt={cfg['dt_s']:.0f}s")
            print(f"{'='*60}")
        t0 = time.time()
        try:
            res = run_single_experiment(body_data, cfg, gm_values,
                                        n_bodies=3, body_names=body_names)
            res["elapsed_s"] = round(time.time() - t0, 1)
            if verbose:
                print(f"  Time: {res['elapsed_s']:.1f}s")
                for bn in ["sun", "earth", "moon"]:
                    bs = res["body_stats"][bn]
                    print(f"  {bn:6s}: max_pos={bs['max_pos_km']:.2e} km, "
                          f"rms={bs['rms_pos_km']:.2e}, max_day={bs['max_day']}")
                print(f"  Overall max: {res['overall_max_pos_km']:.2e} km, "
                      f"{'PASS' if res['threshold_6000km'] else 'EXCEEDS'}")
            results.append(res)
        except Exception as e:
            import traceback
            if verbose:
                traceback.print_exc()
            results.append({"experiment": cfg["name"], "error": str(e)})
    return results


def save_ablation_results(results):
    repo_root = Path(__file__).resolve().parents[2]
    out_dir = repo_root / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    # JSON
    json_path = out_dir / "m3_residual_ablation.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n[Ablation] JSON -> {json_path}")

    # CSV
    csv_path = out_dir / "m3_residual_ablation.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["experiment", "integration", "comparison",
                            "dimension", "dt_s", "body", "max_pos_km",
                            "rms_pos_km", "max_vel_kms", "max_day"])
        w.writeheader()
        for res in results:
            if "error" in res:
                continue
            for bn in ["sun", "earth", "moon"]:
                bs = res["body_stats"][bn]
                w.writerow({"experiment": res["experiment"],
                            "integration": res["integration"],
                            "comparison": res["comparison"],
                            "dimension": res["dimension"],
                            "dt_s": res["dt_s"],
                            "body": bn,
                            "max_pos_km": f"{bs['max_pos_km']:.4e}",
                            "rms_pos_km": f"{bs['rms_pos_km']:.4e}",
                            "max_vel_kms": f"{bs['max_vel_kms']:.4e}",
                            "max_day": bs["max_day"]})
    print(f"[Ablation] CSV -> {csv_path}")


if __name__ == "__main__":
    print("=" * 66)
    print("M3 Residual Ablation: compare integration modes")
    print("=" * 66)

    results = run_ablation(verbose=True)
    save_ablation_results(results)

    print(f"\n{'='*66}")
    print("Summary")
    print(f"{'='*66}")
    print(f"{'Exp':<5} {'Integration':<24} {'Compare':<14} {'Dim':<4} "
          f"{'dt(s)':<7} {'MaxPos(km)':<15} {'Thresh':<8}")
    print("-" * 70)
    for res in results:
        if "error" in res:
            print(f"{res['experiment']:<5} ERROR: {res['error']}")
        else:
            st = "PASS" if res["threshold_6000km"] else "EXCEEDS"
            print(f"{res['experiment']:<5} {res['integration']:<24} "
                  f"{res['comparison']:<14} {res['dimension']:<4} "
                  f"{res['dt_s']:<7.0f} {res['overall_max_pos_km']:<15.2e} {st:<8}")
