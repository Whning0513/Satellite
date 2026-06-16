"""
m7_stepsize_convergence.py
==========================
Step-size convergence around the current legal formal solution.

Metrics per dt (3600, 1800, 900, 450 s):
  - energy_drift (continuous, deterministic 3-body diagnostic)
  - angular_momentum_drift
  - perihelion_AU
  - return_event_distance_km
  - return_vinf_kms (defined only through Earth-return semantics)
  - runtime_s

Convergence order is estimated from energy_drift.
"""

import json, os, csv, sys, time, math, numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import GM_SUN, GM_EARTH, GM_MOON, R_MOON, AU_KM, DT_MAIN, DT_REFINE
from nbody import propagate_nbody, compute_conserved_quantities, GM_SEM
from trajectory import DesignParams, solve_trajectory
from horizons import fetch_sem_vectors, initial_state_from_horizons, state_at_index
from experiments.return_search_tools import search_best_return_event

DT_VALUES = [3600.0, 1800.0, 900.0, 450.0]

def _load_reference_candidate(repo_root: Path) -> dict:
    results = repo_root / "data" / "results"
    for name, key in [
        ("m6_independent_window_search.json", "best_valid_candidate"),
        ("m5_legal_window_search.json", "best_lunar_candidate"),
        ("m5_best_lunar_candidate_verify.json", "candidate"),
    ]:
        path = results / name
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        candidate = data.get(key)
        if candidate:
            return {
                "source_file": name,
                "t0_mjd": float(candidate["t0_mjd"]),
                "r_m_km": float(candidate["r_m_km"]),
                "side": str(candidate["side"]),
                "nominal_return_mjd": float(candidate.get("return_event_mjd", candidate.get("return_epoch_mjd", candidate["t0_mjd"] + 365.0))),
            }
    return {
        "source_file": "built_in_fallback",
        "t0_mjd": 61065.0,
        "r_m_km": R_MOON + 100.0,
        "side": "trailing",
        "nominal_return_mjd": 61431.12,
    }


def run_convergence():
    body_data = fetch_sem_vectors(use_cache=True)
    r0_nominal, v0_nominal = initial_state_from_horizons(body_data, 0)
    gm_sem = [GM_SUN, GM_EARTH, GM_MOON]
    reference = _load_reference_candidate(_REPO)

    results = []

    for dt in DT_VALUES:
        print(f"  dt={dt:.0f}s...", end=" ", flush=True)
        t0_cpu = time.time()

        params = DesignParams(
            t0_mjd=reference["t0_mjd"],
            r_m=reference["r_m_km"],
            side=reference["side"],
            r_p=0.3 * AU_KM,
        )
        traj = solve_trajectory(params, body_data, dt_integrate=dt, verbose=False)
        elapsed = time.time() - t0_cpu

        event = search_best_return_event(
            traj=traj,
            body_data=body_data,
            launch_mjd=reference["t0_mjd"],
            nominal_return_mjd=reference["nominal_return_mjd"],
            threshold_km=1.5e6,
            nominal_window_half_width_days=60.0,
            fallback_window_half_width_days=180.0,
            coarse_step_days=0.5,
            coarse_dt_internal_s=max(dt, 900.0),
            refine_step_s=300.0 if dt <= 900.0 else 600.0,
            max_extra_days=500.0,
        )

        r, v = [ri.copy() for ri in r0_nominal], [vi.copy() for vi in v0_nominal]
        E0, L0 = compute_conserved_quantities(r, v, gm_sem, 3)
        steps_30d = int(30 * 86400 / dt)
        for step in range(steps_30d):
            r, v = propagate_nbody(r, v, dt, gm_sem, n_bodies=3, dt_internal=dt)

        E, L = compute_conserved_quantities(r, v, gm_sem, 3)
        l0_norm = float(np.linalg.norm(L0)) if hasattr(L0, 'shape') else float(abs(L0))
        l_norm = float(np.linalg.norm(L)) if hasattr(L, 'shape') else float(abs(L))
        edrift = abs((E - E0) / E0) if E0 != 0 else -1
        ldrift = abs((l_norm - l0_norm) / l0_norm) if l0_norm != 0 else -1

        result = {
            "dt_s": dt,
            "energy_drift": float(edrift),
            "angular_momentum_drift": float(ldrift),
            "perihelion_AU": round(float(traj.r_p_achieved_km / AU_KM), 6),
            "return_event_distance_km": event["event_distance_km"],
            "return_event_mjd": event["return_event_mjd"],
            "valid_return_event": bool(event["valid_return_event"]),
            "return_vinf_kms": event["return_vinf_kms"],
            "runtime_s": round(elapsed, 1),
        }
        results.append(result)
        print(
            f"rp={result['perihelion_AU']:.4f} AU, "
            f"return_dist={result['return_event_distance_km']:.0f} km, "
            f"edrift={edrift:.2e}"
        )

    finest = results[-1]
    for r in results:
        r["perihelion_error_km_vs_finest"] = round(
            abs(r["perihelion_AU"] - finest["perihelion_AU"]) * AU_KM, 2
        )
        if r["return_event_distance_km"] is not None and finest["return_event_distance_km"] is not None:
            r["return_distance_error_km_vs_finest"] = round(
                abs(float(r["return_event_distance_km"]) - float(finest["return_event_distance_km"])), 2
            )
        else:
            r["return_distance_error_km_vs_finest"] = None
        r["energy_drift_scaled_error_vs_finest"] = round(
            abs(r["energy_drift"] - finest["energy_drift"]) / max(1e-30, finest["energy_drift"]) * 1e3, 4
        )

    orders = {}
    edrifts = np.array([r["energy_drift"] for r in results])
    if len(edrifts) >= 4:
        num = abs(edrifts[0] - edrifts[1])
        den = abs(edrifts[1] - edrifts[2])
        if den > 1e-30 and num > 1e-30:
            orders["energy_drift_order"] = round(math.log(num / den) / math.log(2.0), 2)
        num2 = abs(edrifts[1] - edrifts[2])
        den2 = abs(edrifts[2] - edrifts[3])
        if den2 > 1e-30 and num2 > 1e-30:
            orders["energy_drift_order_fine"] = round(math.log(num2 / den2) / math.log(2.0), 2)

    errs = np.array([r.get("perihelion_error_km_vs_finest", 0) for r in results], dtype=float)
    if len(errs) >= 4 and errs[1] != errs[2] and errs[0] != errs[1]:
        try:
            p = math.log(abs(errs[0] - errs[1]) / abs(errs[1] - errs[2])) / math.log(2.0)
            orders["perihelion_error_order"] = round(p, 2)
        except (ValueError, ZeroDivisionError):
            orders["perihelion_error_order"] = None

    summary = {
        "reference_candidate": reference,
        "dt_values": list(DT_VALUES),
        "results": results,
        "estimated_orders": orders,
        "energy_drift_all_below_1e6": bool(all(r["energy_drift"] < 1e-6 for r in results)),
        "energy_drift_min": float(edrifts.min()),
        "energy_drift_max": float(edrifts.max()),
        "note": (
            "Energy drift is used as the clean convergence observable; "
            "perihelion and Earth-return distance are task-facing observables on the current legal candidate. "
            "return_vinf remains event-gated and is not computed for non-return states."
        ),
    }

    # Save
    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    json_path = out_dir / "m7_stepsize_convergence.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n[M7] Saved to {json_path}")

    csv_path = out_dir / "m7_stepsize_convergence.csv"
    with open(csv_path, "w", newline="") as f:
        fields = [
            "dt_s",
            "energy_drift",
            "angular_momentum_drift",
            "perihelion_AU",
            "return_event_distance_km",
            "return_event_mjd",
            "valid_return_event",
            "return_vinf_kms",
            "perihelion_error_km_vs_finest",
            "return_distance_error_km_vs_finest",
            "energy_drift_scaled_error_vs_finest",
            "runtime_s",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)
    print(f"[M7] Saved to {csv_path}")

    return summary


if __name__ == "__main__":
    print("=" * 66)
    print("M7 Step-size Convergence Study (interpolated + continuous)")
    print("=" * 66)
    res = run_convergence()
    print(f"\n  Energy drift: [{res['energy_drift_min']:.2e}, {res['energy_drift_max']:.2e}]")
    print(f"  Estimated orders: {res['estimated_orders']}")
    print(f"  All below 1e-6: {res['energy_drift_all_below_1e6']}")
    print(f"  Note: {res['note']}")
