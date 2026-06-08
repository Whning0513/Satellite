"""
o2_relativity.py
================
O2: General relativistic correction at perihelion.
Uses 1st-order post-Newtonian Schwarzschild correction.
"""

import json, os, sys, numpy as np, time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))
from constants import GM_SUN, AU_KM
from units import km_to_au
from nbody import propagate_nbody as bary_prop, GM_SEM, vv_step_nbody
from horizons import fetch_sem_vectors, initial_state_from_horizons

C_KMS = 299792.458  # speed of light km/s


def gr_acceleration(r, v, mu=GM_SUN):
    """1st-order PN Schwarzschild correction.
    a_gr = mu/(c^2 r^3) * [(4*mu/r - v^2) * r + 4*(r·v)*v]
    """
    rn = np.linalg.norm(r)
    if rn < 1e-3:
        return np.zeros_like(r)
    c2 = C_KMS**2
    r_dot_v = np.dot(r, v)
    v2 = np.dot(v, v)
    factor = mu / (c2 * rn**3)
    return factor * ((4*mu/rn - v2) * r + 4 * r_dot_v * v)


def propagate_with_gr(r0, v0, dt_total, gm, dt_internal=3600.0):
    """Propagate 3-body with GR correction on all bodies."""
    n_bodies = len(r0)
    r = [ri.copy() for ri in r0]
    v = [vi.copy() for vi in v0]
    n_steps = int(dt_total / dt_internal)
    r_min_sun_gr = np.inf

    for _ in range(n_steps):
        a0 = []
        for i in range(n_bodies):
            a_grav = np.zeros_like(r[i])
            for j in range(n_bodies):
                if i == j: continue
                dr = r[j] - r[i]
                d3 = np.linalg.norm(dr)**3
                if d3 > 0: a_grav += gm[j] * dr / d3
            a_gr = gr_acceleration(r[i], v[i]) if i > 0 else 0
            a0.append(a_grav + a_gr)
        r_new = [r[i] + dt_internal*v[i] + 0.5*dt_internal**2*a0[i] for i in range(n_bodies)]
        a1 = []
        for i in range(n_bodies):
            a_grav = np.zeros_like(r_new[i])
            for j in range(n_bodies):
                if i == j: continue
                dr = r_new[j] - r_new[i]
                d3 = np.linalg.norm(dr)**3
                if d3 > 0: a_grav += gm[j] * dr / d3
            a_gr = gr_acceleration(r_new[i], v[i]) if i > 0 else 0
            a1.append(a_grav + a_gr)
        v = [v[i] + 0.5*dt_internal*(a0[i]+a1[i]) for i in range(n_bodies)]
        r = r_new
        if np.linalg.norm(r[3] - r[0]) < r_min_sun_gr:
            r_min_sun_gr = np.linalg.norm(r[3] - r[0])
    return r, v, r_min_sun_gr


def main():
    bd = fetch_sem_vectors(use_cache=True)
    r0, v0 = initial_state_from_horizons(bd, 0)
    gm = GM_SEM + [0.0]  # 4-body: Sun, Earth, Moon, Rocket

    # Build rocket state: near Earth, heading retrograde
    from trajectory import DesignParams, solve_trajectory
    params = DesignParams(t0_mjd=61066.0, r_m=2237.4, side="trailing", r_p=0.3*AU_KM)
    traj = solve_trajectory(params, bd, verbose=False)

    # Rocket near Earth — use full 3D (Horizons data is 3D)
    # r0[0],v0[0] are (3,) from SSB; traj fields are (2,)
    # Promote rocket to 3D by appending z=0
    v_earth2 = traj.v_earth_t0
    vdir = -v_earth2 / np.linalg.norm(v_earth2)
    r_rocket_2d = traj.r_earth_t0 + 7016 * vdir
    v_rocket_2d = v_earth2 + traj.v_inf_earth * vdir
    # Promote to 3D
    r_rocket = np.array([r_rocket_2d[0], r_rocket_2d[1], 0.0])
    v_rocket = np.array([v_rocket_2d[0], v_rocket_2d[1], 0.0])

    r4 = [r0[0].copy(), r0[1].copy(), r0[2].copy(), r_rocket]
    v4 = [v0[0].copy(), v0[1].copy(), v0[2].copy(), v_rocket]
    gm4 = [GM_SUN, 398600.435507, 4902.800118, 0.0]

    dt_i = 3600.0
    total_s = min(traj.t_total_days * 86400, 60*86400)  # 60 days

    # Newtonian
    t0c = time.time()
    r_n, v_n, rp_n = propagate_with_gr(r4, v4, total_s, gm4, dt_i)
    t_n = time.time() - t0c

    # GR
    t0c = time.time()
    r_g, v_g, rp_g = propagate_with_gr(r4, v4, total_s, gm4, dt_i)
    t_g = time.time() - t0c

    rp_n_au = km_to_au(rp_n)
    rp_g_au = km_to_au(rp_g)
    delta_rp_km = rp_g - rp_n

    # Max GR acceleration ratio
    r_sun_norm = np.linalg.norm(r_n[3] - r_n[0])
    v_rel = np.linalg.norm(v_n[3] - v_n[0])
    a_newton = GM_SUN / r_sun_norm**2
    a_gr_mag = np.linalg.norm(gr_acceleration(r_n[3] - r_n[0], v_n[3] - v_n[0]))

    result = {
        "t0_mjd": 61066.0,
        "propagation_days": total_s / 86400,
        "rp_newtonian_AU": round(rp_n_au, 6),
        "rp_gr_AU": round(rp_g_au, 6),
        "delta_rp_km": round(delta_rp_km, 4),
        "relative_rp_change": round(delta_rp_km / rp_n, 10) if rp_n > 0 else 0,
        "max_a_gr_kms2": round(a_gr_mag, 15),
        "max_a_newton_kms2": round(a_newton, 10),
        "relative_accel_ratio": round(a_gr_mag / a_newton, 12) if a_newton > 0 else 0,
        "note": "GR effect for Sun-Earth-Moon system at ~0.3 AU is extremely small (~1e-8 of Newtonian). "
                "For Mercury (0.4 AU) the effect is ~1e-7. Not measurable in this project's scope.",
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    json_path = out_dir / "o2_relativity.json"
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"[O2] Saved to {json_path}")
    print(f"  Newtonian r_p: {rp_n_au:.6f} AU")
    print(f"  GR r_p:        {rp_g_au:.6f} AU")
    print(f"  Δr_p:          {delta_rp_km:.4f} km")
    print(f"  a_GR / a_N:    {result['relative_accel_ratio']:.2e}")
    print("[O2] Done.")


if __name__ == "__main__":
    main()
