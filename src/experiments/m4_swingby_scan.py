"""
m4_swingby_scan.py
==================
M4 multi-parameter swingby scan — proper perifocal construction + DOP853.

For each (r_m, v_inf, side):
  1. Compute exact hyperbolic orbit in perifocal frame.
  2. Construct initial state at SOI boundary (r=R_SOI) from true anomaly.
  3. Integrate moon-centric two-body with DOP853 (high-precision).
  4. Detect SOI exit via event function (r=R_SOI, vr>0).
  5. Compare with analytic turn angles:
     - δ_inf (asymptotic): from standard 2*arcsin(1/e)
     - δ_finite (finite-SOI): from orbit equation at SOI entry/exit

This distinguishes between:
  - True modeling error (dynamics ≠ analytic formula)
  - Apparent error from finite-SOI vs asymptote definitional difference.

Output:
  data/results/m4_swingby_numeric.json
  data/results/m4_swingby_scan.csv
  data/results/m4_swingby_error_summary.json
"""

import json, os, csv, sys, time, math, numpy as np
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from constants import GM_MOON, R_MOON, R_MOON_SOI, DT_REFINE
from scipy.integrate import solve_ivp

MU = GM_MOON           # km^3/s^2 — moon-centric two-body
R_SOI = R_MOON_SOI     # 66183 km

PARAM_GRID = {
    "r_m_km": [R_MOON + 100, 3000, 5000, 10000, 20000, 50000],
    "v_inf_kms": [1.0, 3.0, 5.0, 8.0, 10.0],
    "side": ["trailing", "leading"],
}


def perifocal_initial_state(r_m, v_inf, side, r_soi=R_SOI):
    """Construct initial state at SOI boundary from hyperbolic orbit elements.

    Returns (r0, v0) in moon-centric inertial frame (2D).
    """
    # --- Hyperbolic orbit elements ---
    e = 1.0 + r_m * v_inf * v_inf / MU   # eccentricity
    p = r_m * (1.0 + e)                  # semi-latus rectum
    h = math.sqrt(MU * p)                # specific angular momentum
    delta_inf = 2.0 * math.asin(1.0 / e) # asymptotic deflection (rad)

    # True anomaly at SOI boundary: R_SOI = p / (1 + e*cos(f))
    cos_f_R = (p / r_soi - 1.0) / e
    cos_f_R = np.clip(cos_f_R, -1.0, 1.0)
    f_R = math.acos(cos_f_R)            # 0 ≤ f_R ≤ π

    # Entry and exit true anomalies
    f_in = -f_R
    f_out = f_R

    # --- Perifocal frame state at entry ---
    def state_at_f(f):
        c, s = math.cos(f), math.sin(f)
        r_pf = np.array([r_soi * c, r_soi * s])
        v_r = MU / h * e * s            # radial velocity
        v_t = MU / h * (1.0 + e * c)    # transverse velocity
        v_pf = np.array([v_r * c - v_t * s,
                         v_r * s + v_t * c])
        return r_pf, v_pf

    # Choose entry/exit based on side
    # For trailing: standard perifocal orientation
    #   Entry at f=-f_R (incoming from below x-axis, approaching periapsis)
    #   Exit at f=+f_R (outgoing above x-axis)
    # For leading: rotate perifocal frame by π
    #   Same hyperbola, but periapsis is on opposite side of Moon
    #   Apply rotation matrix R_z(π) to position and velocity
    #   This makes the rocket approach from the opposite (ahead) side
    if side == "trailing":
        # Standard: entry at f=-f_R (v_r < 0, inward), exit at f=+f_R (v_r > 0, outward)
        r0, v0 = state_at_f(f_in)
    else:
        # Leading: start at f=+f_R (the "exit" side) with reversed velocity.
        # The rocket traces the SAME hyperbola backward, entering from the
        # opposite (ahead) direction. It exits at f=-f_R on the other side.
        # The angle between entry and exit velocity is the same as trailing.
        r_exit, v_exit = state_at_f(f_out)  # f_out = +f_R, v_r > 0
        r0 = r_exit.copy()
        v0 = -v_exit  # now v_r < 0, rocket heads inward

    return r0, v0, e, delta_inf, p, h, f_R


def moon_centric_ode(t, y):
    """RHS for moon-centric 2-body: dy/dt = [v, -μ*r/|r|^3]."""
    r = y[:2]
    v = y[2:]
    r_norm = np.linalg.norm(r)
    a = -MU * r / (r_norm ** 3)
    return np.concatenate([v, a])


def soi_exit_event(t, y):
    """Event: r = R_SOI (crossing outward). Terminate when true."""
    r = np.linalg.norm(y[:2])
    return r - R_SOI


soi_exit_event.terminal = True
soi_exit_event.direction = 1  # only detect r increasing through R_SOI


def soi_entry_event(t, y):
    """Event: r = R_SOI (crossing inward)."""
    r = np.linalg.norm(y[:2])
    return r - R_SOI


soi_entry_event.terminal = False  # don't stop at entry, we already know it
soi_entry_event.direction = -1    # only detect r decreasing through R_SOI


def run_single_case(r_m, v_inf, side) -> dict:
    """Run one analytical + numerical swingby comparison.

    Returns dictionary with both asymptotic and finite-SOI errors.
    """
    # --- Perifocal initial state ---
    r0, v0, e, delta_inf, p, h, f_R = perifocal_initial_state(r_m, v_inf, side)

    # --- Analytical finite-SOI turn angle ---
    # Compute velocity at f_in and f_out in perifocal frame
    def angle_at_f(f1, f2):
        """Angle between velocity vectors at two true anomalies."""
        def v_at_f(f):
            c, s = math.cos(f), math.sin(f)
            vr = MU / h * e * s
            vt = MU / h * (1.0 + e * c)
            return np.array([vr * c - vt * s, vr * s + vt * c])
        v1 = v_at_f(f1)
        v2 = v_at_f(f2)
        cos_a = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-30)
        return math.degrees(math.acos(np.clip(cos_a, -1.0, 1.0)))

    if side == "trailing":
        delta_finite_analytic = angle_at_f(-f_R, f_R)
    else:
        # Leading: rotated by π — same geometry, just flipped.
        # The magnitude of deflection is the same as trailing.
        # The initial condition is the rotation of trailing's entry state.
        delta_finite_analytic = angle_at_f(-f_R, f_R)

    delta_inf_deg = math.degrees(delta_inf)

    # --- Numerical integration (DOP853) ---
    y0 = np.concatenate([r0, v0])

    # Estimate integration time: 3 * SOI / v_inf
    t_max = 3.0 * R_SOI / max(v_inf, 0.1)

    sol = solve_ivp(
        moon_centric_ode,
        [0.0, t_max],
        y0,
        method="DOP853",
        rtol=1e-10,
        atol=1e-12,
        events=soi_exit_event,
        max_step=100.0,
    )

    # Check exit detection
    exit_detected = len(sol.t_events[0]) > 0 if sol.t_events else False

    result = {
        "r_m_km": r_m,
        "v_inf_kms": v_inf,
        "side": side,
        "eccentricity": round(e, 4),
        "f_R_deg": round(math.degrees(f_R), 4),
        "delta_inf_analytic_deg": round(delta_inf_deg, 6),
        "delta_finite_analytic_deg": round(delta_finite_analytic, 6),
        "closest_approach_analytic_km": round(r_m, 1),
    }

    if exit_detected:
        # Exit state
        t_exit = sol.t_events[0][0]
        y_exit = sol.y_events[0][0]
        r_exit = y_exit[:2]
        v_exit = y_exit[2:]

        # Entry state (r0, v0)
        r_entry = r0
        v_entry = v0

        # Closest approach during integration
        r_norms = np.linalg.norm(sol.y[:2, :], axis=0)
        r_min_num = float(np.min(r_norms))
        t_min_idx = int(np.argmin(r_norms))
        # 3-point interpolation for refined peri
        if 0 < t_min_idx < len(sol.t) - 1:
            ts = sol.t[t_min_idx-1:t_min_idx+2]
            rs = r_norms[t_min_idx-1:t_min_idx+2]
            A = np.vstack([ts**2, ts, np.ones_like(ts)]).T
            coeffs = np.linalg.lstsq(A, rs, rcond=None)[0]
            t_min_interp = -coeffs[1] / (2.0 * coeffs[0])
            if ts[0] <= t_min_interp <= ts[-1]:
                r_min_num = float(coeffs[0] * t_min_interp**2 + coeffs[1]*t_min_interp + coeffs[2])

        # Numerical finite deflection (velocity direction difference)
        cos_d_num = np.dot(v_entry, v_exit) / (np.linalg.norm(v_entry) * np.linalg.norm(v_exit) + 1e-30)
        delta_num_deg = float(np.degrees(np.arccos(np.clip(cos_d_num, -1.0, 1.0))))

        # Asymptotic deflection from v_inf at entry/exit
        # For moon-centric 2-body, v_inf = v relative to Moon
        v_inf_in_mag = np.linalg.norm(v_entry)
        v_inf_out_mag = np.linalg.norm(v_exit)
        cos_vinf = np.dot(v_entry, v_exit) / (v_inf_in_mag * v_inf_out_mag + 1e-30)
        delta_numeric_inf_deg = float(np.degrees(np.arccos(np.clip(cos_vinf, -1.0, 1.0))))

        vinf_conservation = abs(v_inf_in_mag / (v_inf_out_mag + 1e-30) - 1.0)

        result.update({
            "delta_numeric_inf_deg": round(delta_numeric_inf_deg, 6),
            "delta_numeric_finite_deg": round(delta_num_deg, 6),
            "error_inf_deg": round(abs(delta_numeric_inf_deg - delta_inf_deg), 6),
            "error_finite_deg": round(abs(delta_num_deg - delta_finite_analytic), 6),
            "closest_approach_numeric_km": round(r_min_num, 1),
            "vinf_in_kms": round(v_inf_in_mag, 6),
            "vinf_out_kms": round(v_inf_out_mag, 6),
            "vinf_conservation_error": round(vinf_conservation, 10),
            "n_integration_steps": len(sol.t),
            "soi_status": "complete",
            "status": "ok",
        })
    else:
        result.update({
            "delta_numeric_inf_deg": None,
            "delta_numeric_finite_deg": None,
            "error_inf_deg": None,
            "error_finite_deg": None,
            "closest_approach_numeric_km": None,
            "vinf_conservation_error": None,
            "n_integration_steps": len(sol.t) if hasattr(sol, 't') else 0,
            "soi_status": "exit_not_detected",
            "status": "partial",
        })

    return result


def run_scan():
    """Full parameter scan."""
    results = []
    tot = len(PARAM_GRID["r_m_km"]) * len(PARAM_GRID["v_inf_kms"]) * len(PARAM_GRID["side"])
    print(f"[M4 scan] {tot} cases ({len(PARAM_GRID['r_m_km'])} r_m × {len(PARAM_GRID['v_inf_kms'])} v_inf × {len(PARAM_GRID['side'])} side)")
    t0 = time.time()
    num_ok = 0

    for r_m in PARAM_GRID["r_m_km"]:
        for v_inf in PARAM_GRID["v_inf_kms"]:
            for side in PARAM_GRID["side"]:
                res = run_single_case(r_m, v_inf, side)
                results.append(res)
                if res["status"] == "ok":
                    num_ok += 1
                status_char = "OK" if res["status"] == "ok" else "!!"
                err_inf = res.get("error_inf_deg", "?")
                err_fin = res.get("error_finite_deg", "?")
                print(f"  [{num_ok}/{tot}] r_m={r_m:.0f}, v_inf={v_inf:.1f}, side={side}: "
                      f"||inf|Err={err_inf}°, finErr={err_fin}° [{status_char}]")

    elapsed = time.time() - t0
    print(f"\n  Done: {num_ok}/{tot} ok, {elapsed:.0f}s")

    # Aggregate by v_inf range
    high_vinf = [r for r in results if r.get("v_inf_kms", 0) >= 3 and r["status"] == "ok"]
    low_vinf = [r for r in results if r.get("v_inf_kms", 0) < 3 and r["status"] == "ok"]

    def agg(rs, label):
        inf_errs = [r["error_inf_deg"] for r in rs if r.get("error_inf_deg") is not None]
        fin_errs = [r["error_finite_deg"] for r in rs if r.get("error_finite_deg") is not None]
        vinf_errs = [r["vinf_conservation_error"] for r in rs if r.get("vinf_conservation_error") is not None]
        if not inf_errs:
            return {"label": label, "n": 0}
        return {
            "label": label,
            "n": len(inf_errs),
            "max_error_inf_deg": round(max(inf_errs), 4),
            "median_error_inf_deg": round(float(np.median(inf_errs)), 4),
            "max_error_finite_deg": round(max(fin_errs), 4) if fin_errs else None,
            "median_error_finite_deg": round(float(np.median(fin_errs)), 4) if fin_errs else None,
            "max_vinf_conservation": round(max(vinf_errs), 10) if vinf_errs else None,
        }

    summary = {
        "num_cases": tot,
        "num_ok": num_ok,
        "num_partial": tot - num_ok,
        "all": agg(results, "all"),
        "high_vinf_ge3_kms": agg(high_vinf, "v_inf >= 3"),
        "low_vinf_lt3_kms": agg(low_vinf, "v_inf < 3"),
        "target": "error_finite_deg < 0.5 (all); error_inf_deg < 0.2 median, < 1 max (v_inf>=3)",
        "note": "Finite-SOI error measures deflection between SOI entry/exit velocity. "
                "Asymptotic error compares with infinite-distance turn angle δ_inf. "
                "Low-v_inf large asymptotic error is expected: strong curvature makes "
                "finite SOI a poor approximation of infinity.",
        "generated_by": "experiments/m4_swingby_scan.py (perifocal + DOP853)",
    }
    return summary, results


def save_scan(summary, results):
    out_dir = _REPO_ROOT / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    # Full JSON
    output = {**summary, "cases": results}
    json_path = out_dir / "m4_swingby_numeric.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"  -> {json_path}")

    # CSV
    csv_path = out_dir / "m4_swingby_scan.csv"
    with open(csv_path, "w", newline="") as f:
        fields = ["r_m_km", "v_inf_kms", "side", "eccentricity", "f_R_deg",
                  "delta_inf_analytic_deg", "delta_finite_analytic_deg",
                  "delta_numeric_inf_deg", "delta_numeric_finite_deg",
                  "error_inf_deg", "error_finite_deg",
                  "vinf_in_kms", "vinf_out_kms", "vinf_conservation_error",
                  "closest_approach_numeric_km", "soi_status", "status"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"  -> {csv_path}")

    # Error summary
    err_path = out_dir / "m4_swingby_error_summary.json"
    with open(err_path, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in summary.items() if k != "cases"}, f, indent=2)
    print(f"  -> {err_path}")


if __name__ == "__main__":
    print("=" * 66)
    print("M4 Swingby Scan — perifocal + DOP853")
    print("=" * 66)
    summary, results = run_scan()
    save_scan(summary, results)

    a = summary.get("all", {})
    hv = summary.get("high_vinf_ge3_kms", {})
    lv = summary.get("low_vinf_lt3_kms", {})

    print(f"\n  All ({a.get('n', 0)} cases):  max_fin_err={a.get('max_error_finite_deg')}°, "
          f"max_inf_err={a.get('max_error_inf_deg')}°, "
          f"med_inf_err={a.get('median_error_inf_deg')}°")
    print(f"  v_inf>=3 ({hv.get('n', 0)}):  max_fin_err={hv.get('max_error_finite_deg')}°, "
          f"med_inf_err={hv.get('median_error_inf_deg')}°, "
          f"max_inf_err={hv.get('max_error_inf_deg')}°")
    print(f"  v_inf<3  ({lv.get('n', 0)}):  max_fin_err={lv.get('max_error_finite_deg')}°, "
          f"max_inf_err={lv.get('max_error_inf_deg')}°")
    print(f"  v_inf conservation: max={a.get('max_vinf_conservation')}")
    print(f"  Status: {summary.get('status', 'unknown')}")
