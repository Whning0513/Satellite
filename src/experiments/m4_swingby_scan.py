"""
m4_swingby_scan.py
==================
M4 多参数 swingby scan: 在 r_m, v_inf, side 网格上比较解析与数值偏转角。

输出:
  data/results/m4_swingby_numeric.json
  data/results/m4_swingby_scan.csv
"""

import json, os, csv, sys, time, numpy as np
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from constants import GM_SUN, GM_EARTH, GM_MOON, R_MOON, R_MOON_SOI, DT_REFINE
from nbody import GM_SEMR, vv_step_nbody
from lunar_swingby import compute_swingby, compute_swingby_turn_angle
from frames import to_heliocentric
from horizons import fetch_sem_vectors, state_at_index


PARAM_GRID = {
    "r_m_km": [R_MOON + 100, 3000, 5000, 10000, 20000, 50000],
    "v_inf_kms": [1.0, 3.0, 5.0, 8.0, 10.0],
    "side": ["trailing", "leading"],
}


def run_single_swingby_case(r_m, v_inf, side, body_data, epoch_idx=100) -> dict:
    """Run one analytical + numerical swingby comparison."""

    # --- Analytical ---
    r_sun3, v_sun3 = state_at_index(body_data, "Sun", epoch_idx)
    r_earth3, v_earth3 = state_at_index(body_data, "Earth", epoch_idx)
    r_moon3, v_moon3 = state_at_index(body_data, "Moon", epoch_idx)

    r_moon = r_moon3[:2].copy()
    v_moon = v_moon3[:2].copy()
    v_moon_dir = v_moon / (np.linalg.norm(v_moon) + 1e-15)

    # v_inf direction: aligned with Moon velocity for trailing, opposite for leading
    if side == "trailing":
        v_inf_vec = v_inf * v_moon_dir
    else:
        v_inf_vec = -v_inf * v_moon_dir
    v_inf_dir_rad = np.arctan2(v_inf_vec[1], v_inf_vec[0])

    an_result = compute_swingby(r_m, v_inf, v_inf_dir_rad, v_moon, side=side)

    # --- Numerical (4-body propagation) ---
    # Impact parameter for hyperbolic trajectory
    a_hyper = GM_MOON / (v_inf * v_inf)
    e_h = 1.0 + r_m * v_inf * v_inf / GM_MOON
    b = a_hyper * np.sqrt(e_h**2 - 1.0)

    perp = np.array([-v_moon_dir[1], v_moon_dir[0]])
    start_dist = 1.5 * R_MOON_SOI

    if side == "trailing":
        # rocket from behind Moon
        r_rocket = r_moon + start_dist * (-v_moon_dir) - b * perp
    else:
        # rocket ahead of Moon
        r_rocket = r_moon + start_dist * v_moon_dir - b * perp
    v_rocket = v_moon + v_inf_vec

    r4 = [r_sun3[:2], r_earth3[:2], r_moon, r_rocket]
    v4 = [v_sun3[:2], v_earth3[:2], v_moon, v_rocket]

    # Propagate through SOI
    dt_st = DT_REFINE
    max_st = int(4.0 * start_dist / (v_inf * dt_st))

    entry_state = None
    exit_state = None
    closest = np.inf
    in_soi = False

    for s in range(max_st):
        moon_dist = np.linalg.norm(r4[3] - r4[2])
        inside = moon_dist < R_MOON_SOI
        if inside and not in_soi:
            entry_state = (r4[3].copy(), v4[3].copy(), r4[2].copy(), v4[2].copy())
            in_soi = True
        elif not inside and in_soi:
            exit_state = (r4[3].copy(), v4[3].copy(), r4[2].copy(), v4[2].copy())
            break
        if moon_dist < closest:
            closest = moon_dist
        r4, v4 = vv_step_nbody(r4, v4, dt_st, GM_SEMR, 4)

    result = {
        "r_m_km": r_m,
        "v_inf_kms": v_inf,
        "side": side,
        "analytical_turn_angle_deg": round(an_result.delta_deg, 4),
        "eccentricity": round(an_result.e, 4),
        "closest_approach_km": round(closest, 1),
    }

    if entry_state is not None and exit_state is not None:
        v_inf_in = entry_state[1] - entry_state[3]
        v_inf_out = exit_state[1] - exit_state[3]
        vi_mag = np.linalg.norm(v_inf_in)
        vo_mag = np.linalg.norm(v_inf_out)
        cos_d = np.dot(v_inf_in, v_inf_out) / (vi_mag * vo_mag + 1e-15)
        delta_num_deg = float(np.degrees(np.arccos(np.clip(cos_d, -1.0, 1.0))))
        vinf_err = abs(vi_mag / (vo_mag + 1e-15) - 1.0)

        result.update({
            "numerical_turn_angle_deg": round(delta_num_deg, 4),
            "angle_error_deg": round(abs(delta_num_deg - an_result.delta_deg), 4),
            "relative_angle_error": round(abs(delta_num_deg - an_result.delta_deg) / an_result.delta_deg, 4) if an_result.delta_deg > 0 else -1,
            "vinf_in_kms": round(vi_mag, 4),
            "vinf_out_kms": round(vo_mag, 4),
            "vinf_conservation_error": round(vinf_err, 6),
            "soi_entry_exit_status": "complete",
            "status": "ok",
        })
    else:
        result.update({
            "numerical_turn_angle_deg": None,
            "angle_error_deg": None,
            "vinf_conservation_error": None,
            "soi_entry_exit_status": "incomplete",
            "status": "partial",
        })

    return result


def run_scan():
    """Full parameter scan."""
    body_data = fetch_sem_vectors(use_cache=True)
    results = []
    num_cases = 0
    num_ok = 0

    tot = len(PARAM_GRID["r_m_km"]) * len(PARAM_GRID["v_inf_kms"]) * len(PARAM_GRID["side"])
    print(f"[M4 scan] {tot} cases ({len(PARAM_GRID['r_m_km'])} r_m × {len(PARAM_GRID['v_inf_kms'])} v_inf × {len(PARAM_GRID['side'])} side)")
    t0 = time.time()

    for r_m in PARAM_GRID["r_m_km"]:
        for v_inf in PARAM_GRID["v_inf_kms"]:
            for side in PARAM_GRID["side"]:
                res = run_single_swingby_case(r_m, v_inf, side, body_data)
                results.append(res)
                num_cases += 1
                if res["status"] == "ok":
                    num_ok += 1
                print(f"  [{num_cases}/{tot}] r_m={r_m:.0f}, v_inf={v_inf:.1f}, side={side}: "
                      f"ana={res['analytical_turn_angle_deg']:.2f}°, "
                      f"num={res.get('numerical_turn_angle_deg','N/A')}, "
                      f"err={res.get('angle_error_deg','N/A')}")

    elapsed = time.time() - t0
    print(f"\n  Done: {num_ok}/{num_cases} ok, {elapsed:.0f}s")

    # Compute aggregate metrics
    angle_errors = [r["angle_error_deg"] for r in results if r.get("angle_error_deg") is not None]
    vinf_errors = [r["vinf_conservation_error"] for r in results if r.get("vinf_conservation_error") is not None]

    summary = {
        "num_cases": num_cases,
        "num_ok": num_ok,
        "num_partial": num_cases - num_ok,
        "max_angle_error_deg": round(max(angle_errors), 4) if angle_errors else None,
        "median_angle_error_deg": round(float(np.median(angle_errors)), 4) if angle_errors else None,
        "max_vinf_conservation_error": round(max(vinf_errors), 6) if vinf_errors else None,
        "status": "done-with-local-validation",
        "generated_by": "experiments/m4_swingby_scan.py",
    }

    return summary, results


def save_scan(summary, results):
    repo_root = Path(__file__).resolve().parents[2]
    out_dir = repo_root / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    output = {**summary, "cases": results}

    json_path = out_dir / "m4_swingby_numeric.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"[M4 scan] Saved to {json_path}")

    csv_path = out_dir / "m4_swingby_scan.csv"
    with open(csv_path, "w", newline="") as f:
        fields = ["r_m_km", "v_inf_kms", "side", "analytical_turn_angle_deg",
                  "numerical_turn_angle_deg", "angle_error_deg", "relative_angle_error",
                  "vinf_in_kms", "vinf_out_kms", "vinf_conservation_error",
                  "closest_approach_km", "eccentricity", "status"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"[M4 scan] Saved to {csv_path}")


if __name__ == "__main__":
    print("=" * 66)
    print("M4 Swingby Parameter Scan")
    print("=" * 66)
    summary, results = run_scan()
    save_scan(summary, results)
    print(f"\n  Summary: max_angle_error={summary['max_angle_error_deg']}°, "
          f"median={summary['median_angle_error_deg']}°, "
          f"max_vinf_err={summary['max_vinf_conservation_error']}")
    print(f"  Status: {summary['status']}")
