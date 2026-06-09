"""
o4plus_powered_mga_optimizer.py
=================================
O4+: Powered MGA-Lambert optimizer.

Extends the frozen O4 Lambert-chain framework by allowing small powered
flyby residuals at Moon and Venus.  This is NOT a replacement of O4.

Chain: Earth(t0) -> Moon(t1) -> Venus(t2) -> perihelion -> Earth(t3)

Optimizer: coarse grid search + custom pattern search refinement.
No scipy.optimize dependency.
"""

import json, os, sys, time, math, csv, itertools
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import (
    GM_SUN, GM_EARTH, GM_MOON, GM_VENUS, AU_KM,
    R_MOON, R_VENUS,
)
from units import km_to_au, au_to_km, day_to_sec, sec_to_day
from lambert import solve_lambert_universal, orbital_elements_from_state
from trajectory import interpolate_state_at_mjd

# =========================
# 1. Ephemeris
# =========================

CACHE_PATH = _REPO / "data" / "cache" / "horizons_semv_2026_2028.json"
SEM_PATH = _REPO / "data" / "sem_horizons_2026-2027.json"


def _load_data():
    if CACHE_PATH.exists():
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        src = d.get("venus_source", "unknown")
        if "Venus" in d and len(d["Venus"].get("x_km", [])) > 0:
            return d, src
    # Fall back to SEM + try ephemeris extension
    from o4_ephemeris_extend import extend_ephemeris
    return extend_ephemeris()


# =========================
# 2. Geometry helpers
# =========================

def angle_between(v1, v2):
    n1 = max(np.linalg.norm(v1), 1e-30)
    n2 = max(np.linalg.norm(v2), 1e-30)
    dot = np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)
    return math.acos(dot)


def turn_feasibility(vinf_in, vinf_out, rp_min, mu_body):
    """Return (required_deg, available_deg, deficit_deg, dv_powered)."""
    vi = np.linalg.norm(vinf_in)
    vo = np.linalg.norm(vinf_out)
    vavg = 0.5 * (vi + vo)
    if vavg < 0.01:
        return 0.0, 180.0, 0.0, 0.0

    req = angle_between(vinf_in, vinf_out)
    e = 1.0 + rp_min * vavg ** 2 / mu_body
    if e <= 1.0:
        avail = 0.0
    else:
        avail = 2.0 * math.asin(1.0 / e)
    deficit = max(0.0, req - avail)
    dv_pow = 2.0 * vavg * math.sin(deficit / 2.0)
    return (math.degrees(req), math.degrees(avail),
            math.degrees(deficit), dv_pow)


# =========================
# 3. Lambert leg solvers
# =========================

def solve_helio(r1, r2, tof_days, mu=GM_SUN, prograde=True, long_way=False):
    tof_s = day_to_sec(tof_days)
    try:
        v1, v2, diag = solve_lambert_universal(
            r1, r2, tof_s, mu, prograde=prograde, long_way=long_way)
        if np.any(np.isnan(v1)) or np.any(np.isnan(v2)):
            return None
        return v1, v2
    except Exception:
        return None


def solve_geo_em(r_moon, r_earth, v_earth, tof_days,
                 prograde=True, long_way=False):
    """Earth-Moon: geocentric relative, GM_Earth."""
    from constants import R_EARTH
    r2 = r_moon - r_earth
    r2n = np.linalg.norm(r2)
    if r2n < 1e-6:
        return None
    r_park = R_EARTH * 1.1
    moon_dir = r2 / r2n
    sign = 1.0 if prograde else -1.0
    r1 = np.array([-moon_dir[1] * sign, moon_dir[0] * sign]) * r_park
    tof_s = day_to_sec(tof_days)
    try:
        v1r, v2r, diag = solve_lambert_universal(
            r1, r2, tof_s, GM_EARTH, prograde=prograde, long_way=long_way)
        if np.any(np.isnan(v1r)) or np.any(np.isnan(v2r)):
            return None
        return v_earth + v1r, v_earth + v2r
    except Exception:
        return None


# =========================
# 4. Chain evaluator
# =========================

def evaluate_candidate(t0, dt_em, dt_mv, dt_ve, branches, body_data):
    """Evaluate a single O4+ chain candidate.

    branches = {"EM": str, "MV": str, "VE": str}
    Each branch is "pro_short", "pro_long".

    Returns dict with full diagnostics, or None if Lambert fails.
    """
    t1 = t0 + dt_em
    t2 = t1 + dt_mv
    t3 = t2 + dt_ve

    # Parse branches
    def parse_branch(s):
        pro = s.startswith("pro")
        long_ = "long" in s
        return pro, long_

    # Interpolate
    try:
        rE0, vE0 = interpolate_state_at_mjd(body_data, "Earth", t0)
        rM1, vM1 = interpolate_state_at_mjd(body_data, "Moon", t1)
        rV2, vV2 = interpolate_state_at_mjd(body_data, "Venus", t2)
        rE3, vE3 = interpolate_state_at_mjd(body_data, "Earth", t3)
    except Exception:
        return None

    pg_em, lw_em = parse_branch(branches["EM"])
    pg_mv, lw_mv = parse_branch(branches["MV"])
    pg_ve, lw_ve = parse_branch(branches["VE"])

    # Leg 1: Earth -> Moon (geocentric)
    leg1 = solve_geo_em(rM1, rE0, vE0, dt_em, prograde=pg_em, long_way=lw_em)
    if leg1 is None:
        return None
    v_dep_E, v_arr_M = leg1
    earth_dep_vinf = np.linalg.norm(v_dep_E - vE0)

    # Leg 2: Moon -> Venus (heliocentric)
    leg2 = solve_helio(rM1, rV2, dt_mv, mu=GM_SUN, prograde=pg_mv, long_way=lw_mv)
    if leg2 is None:
        return None
    v_dep_M, v_arr_V = leg2

    # Moon flyby
    m_vinf_in = v_arr_M - vM1
    m_vinf_out = v_dep_M - vM1
    m_req, m_avail, m_def, m_dv = turn_feasibility(
        m_vinf_in, m_vinf_out, R_MOON + 100.0, GM_MOON)

    # Leg 3: Venus -> Earth (heliocentric)
    leg3 = solve_helio(rV2, rE3, dt_ve, mu=GM_SUN, prograde=pg_ve, long_way=lw_ve)
    if leg3 is None:
        return None
    v_dep_V, v_arr_E = leg3

    # Venus flyby
    v_vinf_in = v_arr_V - vV2
    v_vinf_out = v_dep_V - vV2
    v_req, v_avail, v_def, v_dv = turn_feasibility(
        v_vinf_in, v_vinf_out, R_VENUS + 300.0, GM_VENUS)

    # Earth return
    earth_ret_vinf = np.linalg.norm(v_arr_E - vE3)

    # Perihelion on Venus->Earth leg
    a_ve, e_ve, rp_ve, eps_ve, h_ve = orbital_elements_from_state(
        rV2, v_dep_V, GM_SUN)
    perihelion_au = rp_ve / AU_KM

    # Delta-v budget
    dv_launch = earth_dep_vinf
    dv_reentry = max(0.0, earth_ret_vinf - 15.0)

    dv_total = dv_launch + m_dv + v_dv + dv_reentry

    objective = (
        dv_total
        + 100.0 * max(0.0, perihelion_au - 0.4) ** 2
        + 10.0 * max(0.0, earth_ret_vinf - 15.0) ** 2
        + 10.0 * max(0.0, earth_dep_vinf - 20.0) ** 2
        + 5.0 * max(0.0, m_dv - 5.0) ** 2
        + 5.0 * max(0.0, v_dv - 5.0) ** 2
    )

    # Feasibility
    peri_ok = perihelion_au <= 0.4
    ret_ok = earth_ret_vinf <= 15.0
    dep_ok = earth_dep_vinf <= 20.0
    m_pow_ok = m_dv <= 5.0
    v_pow_ok = v_dv <= 5.0

    feasible_powered = peri_ok and ret_ok and dep_ok and m_pow_ok and v_pow_ok
    feasible_pure = feasible_powered and m_dv < 1e-3 and v_dv < 1e-3

    return {
        "t0_mjd": float(t0),
        "moon_mjd": float(t1),
        "venus_mjd": float(t2),
        "return_mjd": float(t3),
        "dt_EM_days": float(dt_em),
        "dt_MV_days": float(dt_mv),
        "dt_VE_days": float(dt_ve),
        "branches": branches,
        "earth_departure_vinf_kms": round(float(earth_dep_vinf), 4),
        "earth_return_vinf_kms": round(float(earth_ret_vinf), 4),
        "perihelion_AU": round(float(perihelion_au), 6),
        "moon_required_turn_deg": round(float(m_req), 4),
        "moon_available_turn_deg": round(float(m_avail), 4),
        "moon_turn_deficit_deg": round(float(m_def), 4),
        "venus_required_turn_deg": round(float(v_req), 4),
        "venus_available_turn_deg": round(float(v_avail), 4),
        "venus_turn_deficit_deg": round(float(v_def), 4),
        "dv_launch_kms": round(float(dv_launch), 4),
        "dv_moon_powered_kms": round(float(m_dv), 4),
        "dv_venus_powered_kms": round(float(v_dv), 4),
        "dv_reentry_kms": round(float(dv_reentry), 4),
        "dv_total_kms": round(float(dv_total), 4),
        "objective": round(float(objective), 4),
        "feasible_powered": bool(feasible_powered),
        "feasible_pure": bool(feasible_pure),
    }


# =========================
# 5. Pattern search refinement
# =========================

STEPS = {"t0": 5.0, "dt_em": 0.5, "dt_mv": 10.0, "dt_ve": 20.0}


def pattern_refine(cand_keys, body_data, max_eval=3000, n_shrink=6):
    """Custom pattern search around a seed candidate.

    cand_keys = (t0, dt_em, dt_mv, dt_ve, branch_EM, branch_MV, branch_VE)

    Returns best (candidate_dict, n_evals).
    """
    t0, dt_em, dt_mv, dt_ve = cand_keys[:4]
    branches = {"EM": cand_keys[4], "MV": cand_keys[5], "VE": cand_keys[6]}

    best_c = evaluate_candidate(t0, dt_em, dt_mv, dt_ve, branches, body_data)
    if best_c is None:
        return None, 1
    n_evals = 1

    step = {"t0": STEPS["t0"], "dt_em": STEPS["dt_em"],
            "dt_mv": STEPS["dt_mv"], "dt_ve": STEPS["dt_ve"]}

    for shrink in range(n_shrink):
        improved = True
        while improved and n_evals < max_eval:
            improved = False
            for param, s in step.items():
                if s < 1e-6:
                    continue
                for sign in [-1, 1]:
                    if n_evals >= max_eval:
                        break
                    delta = sign * s
                    if param == "t0":
                        nt = t0 + delta
                        nc = evaluate_candidate(nt, dt_em, dt_mv, dt_ve,
                                                branches, body_data)
                    elif param == "dt_em":
                        nc = evaluate_candidate(t0, dt_em + delta, dt_mv, dt_ve,
                                                branches, body_data)
                    elif param == "dt_mv":
                        nc = evaluate_candidate(t0, dt_em, dt_mv + delta, dt_ve,
                                                branches, body_data)
                    elif param == "dt_ve":
                        nc = evaluate_candidate(t0, dt_em, dt_mv, dt_ve + delta,
                                                branches, body_data)
                    n_evals += 1
                    if nc is not None and nc["objective"] < best_c["objective"]:
                        best_c = nc
                        t0 = nc["t0_mjd"]
                        dt_em = nc["dt_EM_days"]
                        dt_mv = nc["dt_MV_days"]
                        dt_ve = nc["dt_VE_days"]
                        improved = True
                        break
                    if n_evals >= max_eval:
                        break
        # Shrink step sizes
        for k in step:
            step[k] *= 0.5

    return best_c, n_evals


# =========================
# 6. Main
# =========================

def main():
    print("=" * 66)
    print("O4+: Powered MGA-Lambert Optimizer")
    print("    Earth(t0) -> Moon -> Venus -> Earth(t3)")
    print("=" * 66)

    print("\n[Step 1] Loading ephemeris...")
    body_data, venus_src = _load_data()
    print(f"  Venus: {venus_src}")

    # ---- Stage 1: Coarse grid ----
    T0_CAND = [61041.0, 61066.0, 61125.0, 61154.0, 61213.0]
    DT_EM = [2, 3, 4, 5, 6, 7]
    DT_MV = [80, 100, 120, 140, 160, 180, 200, 220, 240, 260]
    DT_VE = [180, 240, 300, 360, 450, 540, 630, 730]
    BRANCHES = ["pro_short", "pro_long"]

    print(f"  T0: {len(T0_CAND)} | EM: {len(DT_EM)} | "
          f"MV: {len(DT_MV)} | VE: {len(DT_VE)} | branches: 2 per leg")
    total_est = (len(T0_CAND) * len(DT_EM) * len(DT_MV) * len(DT_VE)
                 * len(BRANCHES) ** 3)
    print(f"  Estimated grid: ~{total_est} combinations")

    print("\n[Step 2] Coarse grid search...")
    all_candidates = []
    t0_phase1 = time.time()

    for t0, dt_em, dt_mv, dt_ve, b_em, b_mv, b_ve in itertools.product(
            T0_CAND, DT_EM, DT_MV, DT_VE, BRANCHES, BRANCHES, BRANCHES):
        br = {"EM": b_em, "MV": b_mv, "VE": b_ve}
        c = evaluate_candidate(t0, dt_em, dt_mv, dt_ve, br, body_data)
        if c is not None:
            all_candidates.append(c)
        if len(all_candidates) % 200 == 0 and len(all_candidates) > 0:
            print(f"    Found {len(all_candidates)} Lambert successes...",
                  end="\r")

    t_phase1 = time.time() - t0_phase1
    print(f"\n  Grid search done in {t_phase1:.0f}s")
    print(f"  Lambert successes: {len(all_candidates)}")

    if not all_candidates:
        print("  No Lambert candidates found. Aborting.")
        return

    # Sort and keep top 50
    all_candidates.sort(key=lambda c: c["objective"])
    top_50 = all_candidates[:50]
    n_fp = sum(1 for c in all_candidates if c["feasible_powered"])
    n_fpu = sum(1 for c in all_candidates if c["feasible_pure"])
    print(f"  Top-50 saved for refinement")
    print(f"  Feasible (powered): {n_fp} / {len(all_candidates)}")
    print(f"  Feasible (pure): {n_fpu} / {len(all_candidates)}")

    best_coarse = top_50[0]
    print(f"\n  Best coarse:")
    print(f"    t0={best_coarse['t0_mjd']:.1f} -> "
          f"M={best_coarse['moon_mjd']:.1f} -> "
          f"V={best_coarse['venus_mjd']:.1f} -> "
          f"E={best_coarse['return_mjd']:.1f}")
    print(f"    peri={best_coarse['perihelion_AU']:.4f} AU, "
          f"ret_vinf={best_coarse['earth_return_vinf_kms']:.1f} km/s")
    print(f"    dv_total={best_coarse['dv_total_kms']:.1f} km/s, "
          f"obj={best_coarse['objective']:.1f}")

    # ---- Stage 2: Pattern search on top seeds ----
    print(f"\n[Step 3] Pattern search refinement on top-10 seeds...")
    t0_phase2 = time.time()
    refined = []
    all_evals_total = 0

    for i, c in enumerate(top_50[:10]):
        keys = (c["t0_mjd"], c["dt_EM_days"], c["dt_MV_days"],
                c["dt_VE_days"],
                c["branches"]["EM"], c["branches"]["MV"], c["branches"]["VE"])
        best_r, n_evals = pattern_refine(keys, body_data,
                                         max_eval=3000, n_shrink=6)
        all_evals_total += n_evals
        if best_r is not None:
            print(f"    [{i+1}/10] obj {c['objective']:.1f} -> "
                  f"{best_r['objective']:.1f} "
                  f"dv_total={best_r['dv_total_kms']:.1f} "
                  f"peri={best_r['perihelion_AU']:.4f} "
                  f"fp={best_r['feasible_powered']} "
                  f"({n_evals} evals)")
            refined.append(best_r)

    t_phase2 = time.time() - t0_phase2
    refined.sort(key=lambda c: c["objective"])
    best = refined[0] if refined else top_50[0]

    n_fp_ref = sum(1 for c in refined if c["feasible_powered"])
    n_fpu_ref = sum(1 for c in refined if c["feasible_pure"])

    print(f"\n  Pattern search done in {t_phase2:.0f}s, "
          f"{all_evals_total} total evals")
    print(f"  Feasible powered: {n_fp_ref} / {len(refined)} refined")
    print(f"  Feasible pure: {n_fpu_ref} / {len(refined)} refined")

    # ---- Best result ----
    total_evals = len(all_candidates) + all_evals_total
    best_c = best
    print(f"\n  Best overall:")
    print(f"    t0={best_c['t0_mjd']:.1f} -> "
          f"M={best_c['moon_mjd']:.1f} -> "
          f"V={best_c['venus_mjd']:.1f} -> "
          f"E={best_c['return_mjd']:.1f}")
    print(f"    branches: EM={best_c['branches']['EM']}, "
          f"MV={best_c['branches']['MV']}, VE={best_c['branches']['VE']}")
    print(f"    perihelion={best_c['perihelion_AU']:.4f} AU")
    print(f"    dep_vinf={best_c['earth_departure_vinf_kms']:.2f} km/s")
    print(f"    ret_vinf={best_c['earth_return_vinf_kms']:.2f} km/s")
    print(f"    Moon deficit={best_c['moon_turn_deficit_deg']:.2f} deg, "
          f"dv={best_c['dv_moon_powered_kms']:.4f} km/s")
    print(f"    Venus deficit={best_c['venus_turn_deficit_deg']:.2f} deg, "
          f"dv={best_c['dv_venus_powered_kms']:.4f} km/s")
    print(f"    dv_total={best_c['dv_total_kms']:.2f} km/s, "
          f"obj={best_c['objective']:.2f}")
    print(f"    feasible_powered={best_c['feasible_powered']}, "
          f"feasible_pure={best_c['feasible_pure']}")

    # ---- Save ----
    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    summary = {
        "task": "O4+ Powered MGA-Lambert optimizer",
        "does_not_overwrite_o4": True,
        "ephemeris_quality": venus_src,
        "optimizer": "coarse grid + custom pattern search",
        "uses_scipy_optimize": False,
        "o4_reference": (
            "O4 is frozen at 18fa865. O4+ extends O4 by allowing "
            "small powered flyby residuals. O4 conclusions unchanged."
        ),
        "num_evaluations": total_evals,
        "num_lambert_success": len(all_candidates),
        "num_feasible_powered": n_fp,
        "num_feasible_pure": n_fpu,
        "num_feasible_powered_refined": n_fp_ref,
        "num_feasible_pure_refined": n_fpu_ref,
        "best_candidate": best_c,
        "top20": refined[:20] if len(refined) >= 20 else refined + top_50[:20 - len(refined)],
    }

    jp = out_dir / "o4plus_powered_mga_optimizer.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nJSON: {jp}")

    # CSV
    all_candidates_sorted = sorted(all_candidates, key=lambda c: c["objective"])
    csv_path = out_dir / "o4plus_powered_mga_candidates.csv"
    if all_candidates_sorted:
        keys = [
            "t0_mjd", "moon_mjd", "venus_mjd", "return_mjd",
            "perihelion_AU", "earth_departure_vinf_kms", "earth_return_vinf_kms",
            "dv_launch_kms", "dv_moon_powered_kms", "dv_venus_powered_kms",
            "dv_reentry_kms", "dv_total_kms", "objective",
            "feasible_powered", "feasible_pure",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for c in all_candidates_sorted[:200]:
                w.writerow({k: c.get(k, "") for k in keys})
        print(f"CSV:  {csv_path}")

    # ---- Pareto plot ----
    try:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(9, 6))
        if all_candidates:
            peri = [c["perihelion_AU"] for c in all_candidates]
            dv_tot = [c["dv_total_kms"] for c in all_candidates]
            ret_vinf = [c["earth_return_vinf_kms"] for c in all_candidates]
            sc = ax.scatter(peri, dv_tot, c=ret_vinf, cmap="viridis",
                           s=10, alpha=0.5, edgecolors="none")
            plt.colorbar(sc, ax=ax, label="Return v_inf (km/s)")
        if best_c:
            ax.scatter([best_c["perihelion_AU"]], [best_c["dv_total_kms"]],
                      c="gold", s=120, marker="*", edgecolors="k",
                      zorder=5, label="Best (refined)")
        # Feasible powered
        fp = [c for c in all_candidates if c["feasible_powered"]]
        if fp:
            ax.scatter([c["perihelion_AU"] for c in fp],
                      [c["dv_total_kms"] for c in fp],
                      c="lime", s=30, marker="o", alpha=0.8,
                      edgecolors="k", linewidths=0.3, label="Feasible powered")
        ax.axvline(0.4, c="red", ls="--", alpha=0.5, label="Perihelion=0.4 AU")
        ax.set_xlabel("Perihelion (AU)");
        ax.set_ylabel("dv_total (km/s)")
        ax.set_title("O4+: Powered MGA-Lambert Candidates")
        ax.legend(fontsize=8); ax.grid(True, alpha=0.3)
        pp = out_dir / "o4plus_powered_mga_pareto.png"
        fig.savefig(pp, dpi=120, bbox_inches="tight"); plt.close()
        print(f"Pareto: {pp}")
    except Exception as e:
        print(f"Pareto plot error: {e}")

    # ---- Timeline plot ----
    try:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 3))
        if best_c:
            events = [
                ("Earth departure", best_c["t0_mjd"]),
                ("Moon flyby", best_c["moon_mjd"]),
                ("Venus flyby", best_c["venus_mjd"]),
                ("Perihelion", best_c["return_mjd"] - 50),
                ("Earth return", best_c["return_mjd"]),
            ]
            names, mjds = zip(*events)
            colors = ["royalblue", "gray", "orange", "red", "green"]
            for i, (n, m) in enumerate(events):
                ax.scatter([m], [0], c=colors[i], s=100, zorder=5)
                ax.annotate(n, (m, 0), textcoords="offset points",
                           xytext=(0, 15), ha="center", fontsize=9)
            ax.plot([mjds[0], mjds[-1]], [0, 0], c="gray", lw=0.5, zorder=1)
            ax.set_xlabel("MJD");
            ax.set_title("O4+: Best Candidate Timeline")
            ax.set_ylim(-1, 1); ax.set_yticks([])
            ax.grid(True, alpha=0.3, axis="x")
            tp = out_dir / "o4plus_powered_mga_timeline.png"
            fig.savefig(tp, dpi=120, bbox_inches="tight"); plt.close()
            print(f"Timeline: {tp}")
    except Exception as e:
        print(f"Timeline plot error: {e}")

    # ---- Summary ----
    print(f"\n{'=' * 66}")
    print(f"O4+: done")
    print(f"  Grid evals: {len(all_candidates)} Lambert successes")
    print(f"  Pattern evals: {all_evals_total}")
    print(f"  Feasible powered (coarse): {n_fp}")
    print(f"  Feasible pure (coarse): {n_fpu}")
    print(f"  Best: obj={best_c['objective']:.1f}, "
          f"dv_total={best_c['dv_total_kms']:.1f} km/s, "
          f"peri={best_c['perihelion_AU']:.4f} AU")
    print(f"  powered: {best_c['feasible_powered']}, "
          f"pure: {best_c['feasible_pure']}")
    print(f"  O4 frozen at 18fa865 — not overwritten.")
    print(f"  O4+ is a new separate extension.")
    print("=" * 66)


if __name__ == "__main__":
    main()
