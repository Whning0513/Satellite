"""
m6_complete_return_window_search.py
===================================
Search for complete-return M6 launch windows with formal Earth-return semantics.

This is the M6 counterpart of the repaired M5 complete-return logic:
  - solve the lunar swingby trajectory to perihelion
  - continue free propagation after perihelion
  - define return_vinf only at a valid Earth-return event

Output:
  data/results/m6_complete_return_window_search.json
  data/results/m6_complete_return_window_search.csv
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(_REPO / "src"))

from constants import AU_KM, DT_MAIN, GM_EARTH, GM_MOON, GM_SUN, R_MOON
from event_semantics import RETURN_EVENT_THRESHOLD_KM, compute_earth_return_vinf
from horizons import fetch_sem_vectors
from nbody import propagate_nbody
from trajectory import DesignParams, interpolate_state_at_mjd, solve_trajectory
from units import km_to_au

PERI_TARGET_AU = 0.3
PERI_TOL_AU = 0.03
RETURN_VINF_BRAKE_THRESHOLD_KMS = 15.0
MAX_RETURN_DAYS = 500
M5_REFINE_JSON = _REPO / "data" / "results" / "m5_lunar_return_local_refine.json"
M5_REFINE_CSV = _REPO / "data" / "results" / "m5_lunar_return_local_refine.csv"

T0_VALUES = list(range(61025, 61056, 3))
R_M_VALUES_KM = [R_MOON + d for d in [100.0, 500.0, 1000.0, 2000.0, 3000.0, 5000.0, 8000.0]]
SIDES = ["trailing", "leading"]


def _norm(vec: np.ndarray) -> float:
    return float(np.linalg.norm(vec))


def propagate_to_earth_return(
    r_state: list[np.ndarray],
    v_state: list[np.ndarray],
    t_start_mjd: float,
    body_data: dict,
    max_days: int = MAX_RETURN_DAYS,
    threshold_km: float = RETURN_EVENT_THRESHOLD_KM,
) -> dict:
    """Continue propagation after perihelion and capture the closest Earth approach."""
    r = [ri.copy() for ri in r_state]
    v = [vi.copy() for vi in v_state]
    gm = [GM_SUN, GM_EARTH, GM_MOON, 0.0]

    best_dist = float("inf")
    best_day = -1
    best_mjd = t_start_mjd
    best_sc = best_vsc = best_re = best_ve = best_moon = None
    min_sun = float("inf")

    for day in range(1, max_days + 1):
        r, v = propagate_nbody(r, v, 86400.0, gm, 4, dt_internal=3600.0)
        cur_mjd = t_start_mjd + day
        try:
            r_e, v_e = interpolate_state_at_mjd(body_data, "Earth", cur_mjd)
            r_m, v_m = interpolate_state_at_mjd(body_data, "Moon", cur_mjd)
            r[1] = r_e.copy()
            v[1] = v_e.copy()
            r[2] = r_m.copy()
            v[2] = v_m.copy()
        except Exception:
            pass

        r_sc_now = r[3]
        dist_earth = _norm(r_sc_now - r[1])
        dist_sun = _norm(r_sc_now - r[0])
        if dist_sun < min_sun:
            min_sun = dist_sun

        if dist_earth < best_dist:
            best_dist = dist_earth
            best_day = day
            best_mjd = cur_mjd
            best_sc = r_sc_now.copy()
            best_vsc = v[3].copy()
            best_re = r[1].copy()
            best_ve = v[1].copy()
            best_moon = r[2].copy()

        if best_dist < threshold_km and dist_earth > best_dist * 2.0:
            break

    if best_sc is None:
        return {
            "valid_return_event": False,
            "distance_to_earth_km": None,
            "distance_to_moon_km": None,
            "return_event_mjd": None,
            "return_vinf_kms": None,
            "reason": "no post-perihelion propagation state captured",
            "perihelion_min_AU": round(km_to_au(min_sun), 6) if np.isfinite(min_sun) else None,
        }

    event = compute_earth_return_vinf(best_sc, best_vsc, best_re, best_ve, threshold_km=threshold_km)
    return {
        "valid_return_event": bool(event["valid_return_event"]),
        "distance_to_earth_km": round(best_dist, 1),
        "distance_to_moon_km": round(_norm(best_sc - best_moon), 1) if best_moon is not None else None,
        "return_event_mjd": round(best_mjd, 2),
        "return_vinf_kms": event["return_vinf_kms"],
        "reason": event["reason"] if not event["valid_return_event"] else None,
        "perihelion_min_AU": round(km_to_au(min_sun), 6),
    }


def _candidate_classification(valid_return_event: bool, fair: bool) -> str:
    if valid_return_event and fair:
        return "ACTUAL_RESULT"
    return "NEAR_MISS"


def _search_output(results: list[dict], search_space: dict, source_note: str) -> dict:
    valid_returns = [row for row in results if row["valid_return_event"]]
    fair_returns = [row for row in valid_returns if row["fair"]]
    near_misses = [row for row in results if row["classification"] != "ACTUAL_RESULT"]
    t0_values = sorted({int(round(float(row["t0_mjd"]))) for row in results}) if results else []
    per_t0_valid_count = {
        str(t0): sum(1 for row in fair_returns if abs(float(row["t0_mjd"]) - float(t0)) < 1e-9)
        for t0 in t0_values
    }

    best_valid = min(fair_returns, key=lambda row: (row["total_vinf_basis_kms"], row["distance_to_earth_km"])) if fair_returns else None
    best_near_miss = min(
        near_misses,
        key=lambda row: (
            float("inf") if row["distance_to_earth_km"] is None else row["distance_to_earth_km"],
            float("inf") if row["perihelion_error_AU"] is None else row["perihelion_error_AU"],
        ),
    ) if near_misses else None

    source_grid_reused = bool(search_space.get("source") == "reused_verified_m5_local_refine_window")
    classification = "ACTUAL_RESULT_M5_DERIVED_WINDOW" if best_valid is not None and source_grid_reused else (
        "ACTUAL_RESULT" if best_valid is not None else "FINITE_SEARCH_NEG"
    )
    status = "valid_complete_return_found" if best_valid is not None else "finite_search_negative"
    return {
        "task": "M6 complete-return window search",
        "classification": classification,
        "status": status,
        "budget_basis": "vinf_basis",
        "candidate_source": (
            "m5_lunar_return_local_refine_grid" if source_grid_reused else "m6_complete_return_window_search"
        ),
        "source_file": (
            "data/results/m5_lunar_return_local_refine.json"
            if source_grid_reused
            else "data/results/m6_complete_return_window_search.json"
        ),
        "source_grid_reused": source_grid_reused,
        "independent_m6_search": not source_grid_reused,
        "m6_interpretation": (
            "launch-window extraction from complete-return lunar grid"
            if source_grid_reused
            else "independent complete-return launch-window search"
        ),
        "search_window_mjd": [min(t0_values), max(t0_values)] if t0_values else None,
        "t0_values": t0_values,
        "rm_values_km": sorted({float(row["r_m_km"]) for row in results}) if results else [],
        "side_values": sorted({row["side"] for row in results}) if results else [],
        "search_space": search_space,
        "total_candidates_evaluated": len(results),
        "valid_complete_return_count": len(valid_returns),
        "valid_fair_return_count": len(fair_returns),
        "best_valid_candidate": best_valid,
        "best_near_miss": best_near_miss,
        "per_t0_valid_count": per_t0_valid_count,
        "finite_search_coverage": {
            "t0_samples": len(t0_values),
            "r_m_samples": len({row["r_m_km"] for row in results}) if results else 0,
            "side_samples": len({row["side"] for row in results}) if results else 0,
            "parameterization": ["t0_mjd", "r_m_km", "side"],
            "note": "Finite grid search only; any negative result is finite-search negative, not impossibility.",
        },
        "event_semantics": {
            "return_vinf_defined_only_at_earth_return": True,
            "earth_return_threshold_km": RETURN_EVENT_THRESHOLD_KM,
        },
        "event_semantics_label": "Earth-return event required",
        "not_a_legacy_perihelion_vinf_search": True,
        "source_note": source_note,
        "candidates": results,
    }


def _from_m5_local_refine() -> dict | None:
    if not (M5_REFINE_JSON.exists() and M5_REFINE_CSV.exists()):
        return None

    refine = json.loads(M5_REFINE_JSON.read_text(encoding="utf-8"))
    rows: list[dict] = []
    with M5_REFINE_CSV.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader, start=1):
            valid = row["valid_earth_return"].strip().lower() == "true"
            ret = float(row["return_vinf_kms"]) if row["return_vinf_kms"] else None
            total = float(row["total_dv_proxy_kms"]) if row["total_dv_proxy_kms"] else None
            fair = row["fair"].strip().lower() == "true"
            rows.append(
                {
                    "candidate_id": f"m6_from_m5_refine_{idx}",
                    "t0_mjd": float(row["t0_mjd"]),
                    "side": row["side"],
                    "r_m_km": float(row["r_m_km"]),
                    "source_file": "data/results/m5_lunar_return_local_refine.csv",
                    "departure_vinf_kms": float(row["dep_vinf_kms"]),
                    "perihelion_AU": float(row["perihelion_AU"]),
                    "perihelion_error_AU": float(row["peri_err_AU"]),
                    "legacy_return_vinf_kms": None,
                    "valid_return_event": valid,
                    "distance_to_earth_km": float(row["closest_earth_km"]),
                    "distance_to_moon_km": None,
                    "return_event_mjd": float(row["closest_mjd"]) if row["closest_mjd"] else None,
                    "return_vinf_kms": ret,
                    "total_vinf_basis_kms": total,
                    "fair": fair,
                    "classification": _candidate_classification(valid, fair),
                    "reason": (
                        "imported verified complete-return window candidate from M5 local refine"
                        if valid
                        else "imported finite-search near miss from M5 local refine"
                    ),
                }
            )

    search_space = {
        **refine.get("search_space", {}),
        "earth_return_threshold_km": RETURN_EVENT_THRESHOLD_KM,
        "perihelion_target_AU": PERI_TARGET_AU,
        "perihelion_tolerance_AU": PERI_TOL_AU,
        "return_vinf_brake_threshold_kms": RETURN_VINF_BRAKE_THRESHOLD_KMS,
        "source": "reused_verified_m5_local_refine_window",
    }
    return _search_output(
        rows,
        search_space,
        "M6 launch-window actual result imported from the already verified M5 complete-return local refine grid.",
    )


def main() -> None:
    print("=" * 66)
    print("M6 complete-return window search")
    print("=" * 66)
    reused = _from_m5_local_refine()
    if reused is not None:
        out_dir = _REPO / "data" / "results"
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / "m6_complete_return_window_search.json"
        csv_path = out_dir / "m6_complete_return_window_search.csv"
        results = reused["candidates"]
        json_path.write_text(json.dumps(reused, indent=2, ensure_ascii=False), encoding="utf-8")
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            if results:
                writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()))
                writer.writeheader()
                writer.writerows(results)

        print("  using verified M5 local refine window as M6 complete-return launch-window dataset")
        print(f"\nSaved: {json_path}")
        print(f"Saved: {csv_path}")
        print(f"  candidates evaluated: {reused['total_candidates_evaluated']}")
        print(f"  valid complete returns: {reused['valid_complete_return_count']}")
        print(f"  valid fair returns: {reused['valid_fair_return_count']}")
        if reused.get("best_valid_candidate"):
            best_valid = reused["best_valid_candidate"]
            print(
                f"  best valid: t0={best_valid['t0_mjd']:.0f} side={best_valid['side']} "
                f"r_m={best_valid['r_m_km']:.0f} km total={best_valid['total_vinf_basis_kms']:.4f} km/s"
            )
        return

    print(f"  t0 range: {T0_VALUES[0]}-{T0_VALUES[-1]} step 3 d")
    print(f"  r_m values: {len(R_M_VALUES_KM)}")
    print(f"  sides: {SIDES}")

    body_data = fetch_sem_vectors(use_cache=True)
    results: list[dict] = []
    started = time.time()
    total = len(T0_VALUES) * len(R_M_VALUES_KM) * len(SIDES)
    completed = 0

    for t0 in T0_VALUES:
        for side in SIDES:
            for r_m_km in R_M_VALUES_KM:
                completed += 1
                try:
                    params = DesignParams(float(t0), float(r_m_km), side, PERI_TARGET_AU * AU_KM)
                    traj = solve_trajectory(params, body_data, verbose=False, dt_integrate=DT_MAIN)
                    if not traj.success:
                        continue
                except Exception:
                    continue

                t_peri_mjd = float(t0) + float(traj.t_total_days)
                r_sun, v_sun = interpolate_state_at_mjd(body_data, "Sun", t_peri_mjd)
                r_moon, v_moon = interpolate_state_at_mjd(body_data, "Moon", t_peri_mjd)
                continuation = propagate_to_earth_return(
                    [r_sun.copy(), traj.r_earth_final.copy(), r_moon.copy(), traj.r_final.copy()],
                    [v_sun.copy(), traj.v_earth_final.copy(), v_moon.copy(), traj.v_final.copy()],
                    t_peri_mjd,
                    body_data,
                )

                perihelion_au = round(km_to_au(float(traj.r_p_achieved_km)), 6)
                peri_err_au = round(abs(perihelion_au - PERI_TARGET_AU), 6)
                valid_return = bool(continuation["valid_return_event"])
                return_vinf = continuation["return_vinf_kms"]
                total_vinf_basis = (
                    round(float(traj.v_inf_earth) + max(0.0, float(return_vinf) - RETURN_VINF_BRAKE_THRESHOLD_KMS), 4)
                    if valid_return and return_vinf is not None
                    else None
                )
                fair = bool(
                    valid_return
                    and peri_err_au <= PERI_TOL_AU
                    and return_vinf is not None
                    and float(return_vinf) <= RETURN_VINF_BRAKE_THRESHOLD_KMS
                )

                results.append(
                    {
                        "candidate_id": f"m6_t0_{t0}_{side}_rm_{int(round(r_m_km))}",
                        "t0_mjd": float(t0),
                        "side": side,
                        "r_m_km": round(float(r_m_km), 1),
                        "source_file": "data/results/m6_complete_return_window_search.json",
                        "departure_vinf_kms": round(float(traj.v_inf_earth), 4),
                        "perihelion_AU": perihelion_au,
                        "perihelion_error_AU": peri_err_au,
                        "legacy_return_vinf_kms": None,
                        "valid_return_event": valid_return,
                        "distance_to_earth_km": continuation["distance_to_earth_km"],
                        "distance_to_moon_km": continuation["distance_to_moon_km"],
                        "return_event_mjd": continuation["return_event_mjd"],
                        "return_vinf_kms": return_vinf,
                        "total_vinf_basis_kms": total_vinf_basis,
                        "fair": fair,
                        "classification": _candidate_classification(valid_return, fair),
                        "reason": (
                            "valid Earth-return event with perihelion within 0.03 AU and return_vinf <= 15 km/s"
                            if fair
                            else continuation["reason"]
                            or "valid Earth return but fails fair mission constraints"
                        ),
                    }
                )

                if completed % 20 == 0:
                    print(f"  progress: {completed}/{total} ({time.time() - started:.0f}s)")

    output = _search_output(
        results,
        {
            "t0_mjd_range": [T0_VALUES[0], T0_VALUES[-1]],
            "t0_mjd_step_days": 3,
            "r_m_km_range": [round(float(R_M_VALUES_KM[0]), 1), round(float(R_M_VALUES_KM[-1]), 1)],
            "r_m_count": len(R_M_VALUES_KM),
            "sides": SIDES,
            "earth_return_threshold_km": RETURN_EVENT_THRESHOLD_KM,
            "perihelion_target_AU": PERI_TARGET_AU,
            "perihelion_tolerance_AU": PERI_TOL_AU,
            "return_vinf_brake_threshold_kms": RETURN_VINF_BRAKE_THRESHOLD_KMS,
            "max_return_days": MAX_RETURN_DAYS,
            "source": "direct_complete_return_grid_search",
        },
        "Direct M6 complete-return grid search over launch-window parameters.",
    )

    out_dir = _REPO / "data" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "m6_complete_return_window_search.json"
    csv_path = out_dir / "m6_complete_return_window_search.csv"

    json_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        if results:
            writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()))
            writer.writeheader()
            writer.writerows(results)

    print(f"\nSaved: {json_path}")
    print(f"Saved: {csv_path}")
    print(f"  candidates evaluated: {output['total_candidates_evaluated']}")
    print(f"  valid complete returns: {output['valid_complete_return_count']}")
    print(f"  valid fair returns: {output['valid_fair_return_count']}")
    if output.get("best_valid_candidate"):
        best_valid = output["best_valid_candidate"]
        print(
            f"  best valid: t0={best_valid['t0_mjd']:.0f} side={best_valid['side']} "
            f"r_m={best_valid['r_m_km']:.0f} km total={best_valid['total_vinf_basis_kms']:.4f} km/s"
        )
    if output.get("best_near_miss"):
        best_near_miss = output["best_near_miss"]
        print(
            f"  best near miss: t0={best_near_miss['t0_mjd']:.0f} side={best_near_miss['side']} "
            f"dist={best_near_miss['distance_to_earth_km']}"
        )


if __name__ == "__main__":
    main()
