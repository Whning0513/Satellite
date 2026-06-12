"""
m6_independent_spotcheck.py
===========================
Recompute a small set of M6 candidates from parameters to confirm that
the derived launch-window result is not merely reading stored M5 values.

Output:
  data/results/m6_independent_spotcheck.json
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(_REPO / "src"))

from constants import AU_KM, DT_MAIN, GM_EARTH, GM_MOON, GM_SUN
from event_semantics import RETURN_EVENT_THRESHOLD_KM, compute_earth_return_vinf
from horizons import fetch_sem_vectors
from nbody import propagate_nbody
from trajectory import DesignParams, interpolate_state_at_mjd, solve_trajectory

RESULTS = _REPO / "data" / "results"
M6_JSON = RESULTS / "m6_complete_return_window_search.json"


def _norm(vec: np.ndarray) -> float:
    return float(np.linalg.norm(vec))


def _propagate_candidate(candidate: dict, body_data: dict) -> dict:
    params = DesignParams(
        float(candidate["t0_mjd"]),
        float(candidate["r_m_km"]),
        candidate["side"],
        0.3 * AU_KM,
    )
    traj = solve_trajectory(params, body_data, verbose=False, dt_integrate=DT_MAIN)
    t_peri_mjd = float(candidate["t0_mjd"]) + float(traj.t_total_days)
    r_sun, v_sun = interpolate_state_at_mjd(body_data, "Sun", t_peri_mjd)
    r_moon, v_moon = interpolate_state_at_mjd(body_data, "Moon", t_peri_mjd)
    r = [r_sun.copy(), traj.r_earth_final.copy(), r_moon.copy(), traj.r_final.copy()]
    v = [v_sun.copy(), traj.v_earth_final.copy(), v_moon.copy(), traj.v_final.copy()]
    gm = [GM_SUN, GM_EARTH, GM_MOON, 0.0]

    best_dist = float("inf")
    best_mjd = t_peri_mjd
    best_sc = best_vsc = best_re = best_ve = None
    for day in range(1, 501):
        r, v = propagate_nbody(r, v, 86400.0, gm, 4, dt_internal=3600.0)
        cur_mjd = t_peri_mjd + day
        try:
            r_e, v_e = interpolate_state_at_mjd(body_data, "Earth", cur_mjd)
            r_m, v_m = interpolate_state_at_mjd(body_data, "Moon", cur_mjd)
            r[1] = r_e.copy()
            v[1] = v_e.copy()
            r[2] = r_m.copy()
            v[2] = v_m.copy()
        except Exception:
            pass
        dist = _norm(r[3] - r[1])
        if dist < best_dist:
            best_dist = dist
            best_mjd = cur_mjd
            best_sc = r[3].copy()
            best_vsc = v[3].copy()
            best_re = r[1].copy()
            best_ve = v[1].copy()
        if best_dist < RETURN_EVENT_THRESHOLD_KM and dist > best_dist * 2.0:
            break

    event = compute_earth_return_vinf(best_sc, best_vsc, best_re, best_ve, threshold_km=RETURN_EVENT_THRESHOLD_KM)
    return {
        "distance_to_earth_km": round(best_dist, 1),
        "return_event_mjd": round(best_mjd, 2),
        "return_vinf_kms": event["return_vinf_kms"],
        "valid_return_event": bool(event["valid_return_event"]),
    }


def _select_candidates(data: dict) -> list[dict]:
    best_valid = data.get("best_valid_candidate")
    near_miss = data.get("best_near_miss")
    valid_neighbors = [
        row for row in data.get("candidates", [])
        if row.get("classification") == "ACTUAL_RESULT"
        and row.get("candidate_id") != best_valid.get("candidate_id")
        and abs(float(row.get("t0_mjd", 0)) - float(best_valid.get("t0_mjd", 0))) <= 3.0
    ] if best_valid else []
    neighbor = valid_neighbors[0] if valid_neighbors else None
    chosen = [c for c in [best_valid, neighbor, near_miss] if c]
    # de-duplicate by candidate_id
    unique = []
    seen = set()
    for row in chosen:
        cid = row["candidate_id"]
        if cid not in seen:
            seen.add(cid)
            unique.append(row)
    return unique


def main() -> None:
    if not M6_JSON.exists():
        raise FileNotFoundError("data/results/m6_complete_return_window_search.json missing")
    data = json.loads(M6_JSON.read_text(encoding="utf-8"))
    body_data = fetch_sem_vectors(use_cache=True)

    checks = []
    max_dist_err = 0.0
    max_vinf_err = 0.0
    for candidate in _select_candidates(data):
        recomputed = _propagate_candidate(candidate, body_data)
        source_dist = candidate.get("distance_to_earth_km")
        source_vinf = candidate.get("return_vinf_kms")
        dist_err = abs(float(source_dist) - float(recomputed["distance_to_earth_km"])) if source_dist is not None else None
        if source_vinf is None or recomputed["return_vinf_kms"] is None:
            vinf_err = 0.0 if source_vinf is None and recomputed["return_vinf_kms"] is None else None
        else:
            vinf_err = abs(float(source_vinf) - float(recomputed["return_vinf_kms"]))

        if dist_err is not None:
            max_dist_err = max(max_dist_err, dist_err)
        if vinf_err is not None:
            max_vinf_err = max(max_vinf_err, vinf_err)

        status = "PASS"
        if candidate.get("classification") == "ACTUAL_RESULT" and not recomputed["valid_return_event"]:
            status = "RED"
        elif vinf_err is not None and vinf_err > 0.1:
            status = "WARN"
        elif dist_err is not None and dist_err > 5000.0:
            status = "WARN"

        checks.append(
            {
                "candidate_id": candidate["candidate_id"],
                "candidate_classification": candidate.get("classification"),
                "source_row_distance_to_earth_km": source_dist,
                "recomputed_distance_to_earth_km": recomputed["distance_to_earth_km"],
                "source_return_vinf_kms": source_vinf,
                "recomputed_return_vinf_kms": recomputed["return_vinf_kms"],
                "distance_abs_error_km": round(dist_err, 3) if dist_err is not None else None,
                "return_vinf_abs_error_kms": round(vinf_err, 6) if vinf_err is not None else None,
                "valid_return_event_recomputed": recomputed["valid_return_event"],
                "status": status,
            }
        )

    overall = "PASS" if all(row["status"] == "PASS" for row in checks) else (
        "WARN" if all(row["status"] != "RED" for row in checks) else "RED"
    )
    payload = {
        "task": "M6 independent spotcheck",
        "source_file": "data/results/m6_complete_return_window_search.json",
        "candidate_source": data.get("candidate_source"),
        "source_grid_reused": data.get("source_grid_reused"),
        "independent_m6_search": data.get("independent_m6_search"),
        "candidates_recomputed": len(checks),
        "max_distance_abs_error_km": round(max_dist_err, 3),
        "max_return_vinf_abs_error_kms": round(max_vinf_err, 6),
        "results": checks,
        "status": overall,
    }

    out = RESULTS / "m6_independent_spotcheck.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved: {out}")
    print(f"status = {overall}")
    print(f"candidates recomputed = {len(checks)}")
    print(f"max distance error = {payload['max_distance_abs_error_km']}")
    print(f"max return_vinf error = {payload['max_return_vinf_abs_error_kms']}")


if __name__ == "__main__":
    main()
