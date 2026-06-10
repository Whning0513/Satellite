"""
o7_worker.py
=============
O7: Process-safe worker functions for multiprocess parallel trajectory evaluation.

Each subprocess independently loads the JPL Horizons cache from disk,
so no pickling of large dicts across process boundaries is needed.
"""

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SRC = str(_REPO / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from constants import AU_KM
from trajectory import DesignParams, solve_trajectory
from horizons import fetch_sem_vectors


def run_one_trajectory(params_tuple):
    """Run a single trajectory solve in a subprocess.

    Parameters
    ----------
    params_tuple : (mjd, r_m_km, side, r_p_km)
        Design parameters as a plain tuple (picklable).

    Returns
    -------
    dict with trajectory results.
    """
    t0_mjd, r_m_km, side, r_p_km = params_tuple
    body_data = fetch_sem_vectors(use_cache=True)

    params = DesignParams(
        t0_mjd=t0_mjd, r_m=r_m_km, side=side, r_p=r_p_km,
    )
    traj = solve_trajectory(params, body_data, verbose=False)

    return {
        "t0_mjd": float(t0_mjd),
        "success": bool(traj.success),
        "rp_AU": float(round(traj.r_p_achieved_km / AU_KM, 4)),
        "r_p_design_AU": float(round(r_p_km / AU_KM, 4)),
        "v_launch_kms": float(round(traj.v_launch, 4)),
        "v_reentry_kms": float(round(traj.v_reentry, 4)),
        "dist_moon_min_km": float(round(traj.dist_moon_min, 1)),
        "t_total_days": float(round(traj.t_total_days, 2)),
    }


def run_mjd_chunk(chunk_args):
    """Run a chunk of MJDs in batch within a subprocess.

    Each process loads the Horizons cache once and evaluates all
    MJDs in its chunk, minimising per-task overhead.

    Parameters
    ----------
    chunk_args : (chunk_id, [mjd, ...], r_m_km, side, r_p_km)

    Returns
    -------
    list of result dicts.
    """
    chunk_id, mjd_list, r_m_km, side, r_p_km = chunk_args
    body_data = fetch_sem_vectors(use_cache=True)

    results = []
    for t0_mjd in mjd_list:
        params = DesignParams(
            t0_mjd=t0_mjd, r_m=r_m_km, side=side, r_p=r_p_km,
        )
        traj = solve_trajectory(params, body_data, verbose=False)
        results.append({
            "t0_mjd": float(t0_mjd),
            "success": bool(traj.success),
            "rp_AU": float(round(traj.r_p_achieved_km / AU_KM, 4)),
            "v_launch_kms": float(round(traj.v_launch, 4)),
        })
    return {"chunk_id": chunk_id, "results": results}
