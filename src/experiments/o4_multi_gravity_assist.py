"""
o4_multi_gravity_assist.py
===========================
O4: Multi-gravity-assist patched-conic chain search.

Search: Earth(t0) -> Moon(t1) -> Venus(t2) -> Earth(t3)

Each leg uses the universal-variable Lambert solver with the correct
central body GM:
  Leg 1 (Earth->Moon):   Earth GM, Earth-centred frame
  Leg 2 (Moon->Venus):   Sun GM, heliocentric frame (SSB)
  Leg 3 (Venus->Earth):  Sun GM, heliocentric frame (SSB)

Flyby feasibility is assessed via required-turn vs available-turn
at minimum periapsis (Moon and Venus).

This is a preliminary patched-conic chain exploration, not full optimal
control. Results identify qualitatively interesting multi-flyby
candidates for further refinement.
"""

import json, os, sys, math, itertools, csv
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import (
    GM_SUN, GM_EARTH, GM_MOON, GM_VENUS, AU_KM,
    R_MOON, R_VENUS, R_SUN,
)
from units import km_to_au, au_to_km, day_to_sec, sec_to_day
from lambert import solve_lambert_universal, orbital_elements_from_state
from trajectory import interpolate_state_at_mjd
from horizons import fetch_sem_vectors

# =========================
# 1. Ephemeris loading
# =========================

def _load_body_data():
    """Load ephemeris — try extended cache first, fall back to SEM-only."""
    ext_path = _REPO / "data" / "cache" / "horizons_semv_2026_2028.json"
    if ext_path.exists():
        with open(ext_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        venus_source = data.get("venus_source", "unknown")
        print(f"  Loaded extended ephemeris (Venus: {venus_source})")
        if "Venus" in data and len(data["Venus"].get("x_km", [])) > 0:
            return data, venus_source

    print("  Extended cache not found; trying to generate...")
    try:
        from o4_ephemeris_extend import extend_ephemeris
        data, venus_source = extend_ephemeris()
        return data, venus_source
    except Exception as e:
        print(f"  Ephemeris extension failed: {e}")
        data = fetch_sem_vectors(use_cache=True)
        return data, "no_venus"


# =========================
# 2. Geometry helpers
# =========================

def angle_between(v1, v2):
    """Angle (radians) between two vectors."""
    n1 = max(np.linalg.norm(v1), 1e-30)
    n2 = max(np.linalg.norm(v2), 1e-30)
    dot = np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)
    return math.acos(dot)


def turn_feasibility(v_inf_in_vec, v_inf_out_vec, rp_min_km, mu_body):
    """Compute required turn and available turn at min periapsis.

    Returns (required_turn_deg, available_turn_deg, deficit_deg).
    deficit > 0 means the flyby cannot achieve the needed turn.
    """
    v_inf_in = np.linalg.norm(v_inf_in_vec)
    v_inf_out = np.linalg.norm(v_inf_out_vec)
    v_inf = 0.5 * (v_inf_in + v_inf_out)

    if v_inf < 0.01:
        return 0.0, 180.0, 0.0

    # Required turn angle
    required_turn = angle_between(v_inf_in_vec, v_inf_out_vec)

    # Available maximum turn at minimum periapsis
    e = 1.0 + rp_min_km * v_inf ** 2 / mu_body
    if e <= 1.0:
        available_turn = 0.0
    else:
        available_turn = 2.0 * math.asin(1.0 / e)

    deficit = max(0.0, required_turn - available_turn)
    return (math.degrees(required_turn), math.degrees(available_turn),
            math.degrees(deficit))


# =========================
# 3. Lambert leg solvers
# =========================

def solve_heliocentric_leg(r1_ssb, r2_ssb, tof_days, mu=GM_SUN,
                           prograde=True, long_way=False):
    """Solve a heliocentric Lambert leg in SSB coordinates."""
    tof_s = day_to_sec(tof_days)
    try:
        v1, v2, diag = solve_lambert_universal(
            r1_ssb, r2_ssb, tof_s, mu,
            prograde=prograde, long_way=long_way,
        )
        if np.any(np.isnan(v1)) or np.any(np.isnan(v2)):
            return None
        return {"v1_kms": v1, "v2_kms": v2}
    except Exception:
        return None


def solve_geocentric_leg(r_moon_ssb, r_earth_ssb, v_earth_ssb,
                         tof_days, mu=GM_EARTH,
                         prograde=True, long_way=False):
    """Solve an Earth-centred Lambert leg (e.g. Earth->Moon).

    Uses parking orbit radius (1.1 * R_EARTH) as departure point, in the
    direction of the Earth-relative Moon position.  Converts velocities
    back to SSB frame.
    """
    from constants import R_EARTH
    tof_s = day_to_sec(tof_days)
    # Moon position relative to Earth
    r2_rel = r_moon_ssb - r_earth_ssb
    r2_norm = np.linalg.norm(r2_rel)
    if r2_norm < 1e-6:
        return None

    # Departure from parking orbit radius with ~90 deg lead angle so the
    # Lambert solver has a non-zero transfer angle.
    r_park = R_EARTH * 1.1  # ~7016 km
    # Rotate the Moon direction by +90 deg for prograde, -90 for retrograde
    moon_dir = r2_rel / r2_norm
    sign = 1.0 if prograde else -1.0
    r1_rel = np.array([-moon_dir[1] * sign, moon_dir[0] * sign]) * r_park

    try:
        v1_rel, v2_rel, diag = solve_lambert_universal(
            r1_rel, r2_rel, tof_s, mu,
            prograde=prograde, long_way=long_way,
        )
        if np.any(np.isnan(v1_rel)) or np.any(np.isnan(v2_rel)):
            return None
        # Convert back to SSB
        v1_ssb = v_earth_ssb + v1_rel
        v2_ssb = v_earth_ssb + v2_rel
        return {"v1_kms": v1_ssb, "v2_kms": v2_ssb}
    except Exception:
        return None


# =========================
# 4. Main chain search
# =========================

def main():
    print("=" * 66)
    print("O4: Multi-Gravity-Assist Chain Search")
    print("    Earth -> Moon -> Venus -> Earth")
    print("=" * 66)

    # ---- Load ephemeris ----
    print("\n[Step 1] Loading ephemeris...")
    body_data, venus_source = _load_body_data()
    print(f"  Venus ephemeris source: {venus_source}")
    has_venus = "Venus" in body_data and len(body_data["Venus"].get("x_km", [])) > 0

    if not has_venus:
        print("  WARNING: Venus not in cache. Generating analytic fallback...")
        from o4_ephemeris_extend import _venus_analytic_fallback
        venus_data, _ = _venus_analytic_fallback()
        body_data["Venus"] = venus_data["Venus"]
        venus_source = "analytic_circular_fallback"

    # ---- Search grid ----
    print("\n[Step 2] Building search grid...")

    t0_candidates = [61041.0, 61066.0, 61125.0, 61154.0, 61213.0]  # all 5 M6 windows
    moon_tof_days   = [3, 4, 5, 7, 10]          # Earth->Moon (days, realistic range)
    venus_tof_days  = [60, 80, 100, 120, 160, 200, 240]  # Moon->Venus
    return_tof_days = [200, 250, 300, 350, 450, 550]      # Venus->Earth
    branches = [(True, False), (True, True)]

    print(f"  t0: {t0_candidates}")
    print(f"  Moon->Venus TOF: {venus_tof_days} days")
    print(f"  Venus->Earth TOF: {return_tof_days} days")
    total = (len(t0_candidates) * len(moon_tof_days) * len(venus_tof_days)
             * len(return_tof_days) * len(branches)**3)
    print(f"  Grid combos: ~{total}")

    R_MOON_MIN = R_MOON + 100.0
    R_VENUS_MIN = R_VENUS + 300.0
    R_SUN_MIN = R_SUN * 2.0   # Avoid Sun collision
    V_DEPART_MAX = 20.0
    V_RETURN_MAX = 15.0
    PERI_MAX_AU = 0.4         # Must pass near Sun
    PERI_MIN_AU = km_to_au(R_SUN_MIN)  # But not too close

    # ---- Search ----
    print("\n[Step 3] Searching chain candidates...")
    candidates = []

    for t0 in t0_candidates:
        r_earth_t0, v_earth_t0 = interpolate_state_at_mjd(body_data, "Earth", t0)

        for d_moon in moon_tof_days:
            t1 = t0 + d_moon
            try:
                r_moon_t1, v_moon_t1 = interpolate_state_at_mjd(body_data, "Moon", t1)
            except Exception:
                continue

            for d_venus in venus_tof_days:
                t2 = t1 + d_venus
                try:
                    r_venus_t2, v_venus_t2 = interpolate_state_at_mjd(body_data, "Venus", t2)
                except Exception:
                    continue

                for d_return in return_tof_days:
                    t3 = t2 + d_return
                    try:
                        r_earth_t3, v_earth_t3 = interpolate_state_at_mjd(body_data, "Earth", t3)
                    except Exception:
                        continue

                    # Leg 1: Earth -> Moon (Earth-centred Lambert)
                    for pg1, lw1 in branches:
                        leg1 = solve_geocentric_leg(
                            r_moon_t1, r_earth_t0, v_earth_t0,
                            d_moon, mu=GM_EARTH, prograde=pg1, long_way=lw1,
                        )
                        if leg1 is None:
                            continue
                        v_dep_earth = leg1["v1_kms"]
                        v_arr_moon = leg1["v2_kms"]
                        branch_em = f"{'pro' if pg1 else 'retro'}_{'long' if lw1 else 'short'}"

                        earth_dep_vinf = np.linalg.norm(v_dep_earth - v_earth_t0)
                        if earth_dep_vinf > V_DEPART_MAX:
                            continue

                        # Leg 2: Moon -> Venus (heliocentric Lambert)
                        for pg2, lw2 in branches:
                            leg2 = solve_heliocentric_leg(
                                r_moon_t1, r_venus_t2, d_venus,
                                mu=GM_SUN, prograde=pg2, long_way=lw2,
                            )
                            if leg2 is None:
                                continue
                            v_dep_moon = leg2["v1_kms"]
                            v_arr_venus = leg2["v2_kms"]
                            branch_mv = f"{'pro' if pg2 else 'retro'}_{'long' if lw2 else 'short'}"

                            # Moon flyby turn
                            moon_vinf_in = v_arr_moon - v_moon_t1
                            moon_vinf_out = v_dep_moon - v_moon_t1
                            moon_req, moon_avail, moon_def = turn_feasibility(
                                moon_vinf_in, moon_vinf_out, R_MOON_MIN, GM_MOON,
                            )

                            # Leg 3: Venus -> Earth (heliocentric Lambert)
                            for pg3, lw3 in branches:
                                leg3 = solve_heliocentric_leg(
                                    r_venus_t2, r_earth_t3, d_return,
                                    mu=GM_SUN, prograde=pg3, long_way=lw3,
                                )
                                if leg3 is None:
                                    continue
                                v_dep_venus = leg3["v1_kms"]
                                v_arr_earth = leg3["v2_kms"]
                                branch_ve = f"{'pro' if pg3 else 'retro'}_{'long' if lw3 else 'short'}"

                                # Venus flyby turn
                                venus_vinf_in = v_arr_venus - v_venus_t2
                                venus_vinf_out = v_dep_venus - v_venus_t2
                                venus_req, venus_avail, venus_def = turn_feasibility(
                                    venus_vinf_in, venus_vinf_out, R_VENUS_MIN, GM_VENUS,
                                )

                                # Earth return
                                earth_return_vinf = np.linalg.norm(v_arr_earth - v_earth_t3)
                                dv_reentry = max(0.0, earth_return_vinf - V_RETURN_MAX)

                                # Perihelion on Venus->Earth leg
                                a_ve, e_ve, rp_ve, eps_ve, h_ve = orbital_elements_from_state(
                                    r_venus_t2, v_dep_venus, GM_SUN,
                                )
                                perihelion_au = rp_ve / AU_KM

                                # Scoring
                                # Feasibility
                                moon_ok = moon_def <= 5.0
                                venus_ok = venus_def <= 5.0
                                peri_ok = PERI_MIN_AU <= perihelion_au <= PERI_MAX_AU
                                return_ok = earth_return_vinf <= V_RETURN_MAX
                                depart_ok = earth_dep_vinf <= V_DEPART_MAX

                                if moon_ok and venus_ok and peri_ok and return_ok and depart_ok:
                                    status = "feasible_ish"
                                else:
                                    status = "candidate"

                                total_tof = d_moon + d_venus + d_return

                                score = (
                                    earth_dep_vinf
                                    + max(0.0, earth_return_vinf - V_RETURN_MAX)
                                    + 5.0 * max(0.0, perihelion_au - 0.4)
                                    + 10.0 * max(0.0, moon_def / 90.0)
                                    + 10.0 * max(0.0, venus_def / 90.0)
                                    + 0.1 * total_tof / 100.0
                                )

                                cand = {
                                    "t0_mjd": float(t0),
                                    "moon_mjd": float(t1),
                                    "venus_mjd": float(t2),
                                    "return_mjd": float(t3),
                                    "total_tof_days": float(total_tof),
                                    "branches": {
                                        "earth_moon": branch_em,
                                        "moon_venus": branch_mv,
                                        "venus_earth": branch_ve,
                                    },
                                    "earth_departure_vinf_kms": round(float(earth_dep_vinf), 4),
                                    "moon_vinf_in_kms": round(float(np.linalg.norm(moon_vinf_in)), 4),
                                    "moon_vinf_out_kms": round(float(np.linalg.norm(moon_vinf_out)), 4),
                                    "moon_required_turn_deg": round(float(moon_req), 4),
                                    "moon_available_turn_deg": round(float(moon_avail), 4),
                                    "moon_turn_deficit_deg": round(float(moon_def), 4),
                                    "venus_vinf_in_kms": round(float(np.linalg.norm(venus_vinf_in)), 4),
                                    "venus_vinf_out_kms": round(float(np.linalg.norm(venus_vinf_out)), 4),
                                    "venus_required_turn_deg": round(float(venus_req), 4),
                                    "venus_available_turn_deg": round(float(venus_avail), 4),
                                    "venus_turn_deficit_deg": round(float(venus_def), 4),
                                    "perihelion_AU": round(float(perihelion_au), 6),
                                    "earth_return_vinf_kms": round(float(earth_return_vinf), 4),
                                    "dv_reentry_kms": round(float(dv_reentry), 4),
                                    "score": round(float(score), 4),
                                    "status": status,
                                }
                                candidates.append(cand)

    # ---- Sort and rank ----
    print(f"\n[Step 4] Ranking {len(candidates)} candidates...")
    candidates.sort(key=lambda c: c["score"])

    feasible = [c for c in candidates if c["status"] == "feasible_ish"]
    lambert_ok = [c for c in candidates if c["status"] == "candidate"]

    print(f"  Lambert successes: {len(lambert_ok) + len(feasible)}")
    print(f"  Feasible-ish:      {len(feasible)}")
    if candidates:
        best = candidates[0]
        print(f"  Best:")
        print(f"    t0={best['t0_mjd']:.1f} -> Moon {best['moon_mjd']:.1f}"
              f" -> Venus {best['venus_mjd']:.1f} -> Return {best['return_mjd']:.1f}")
        print(f"    dep_vinf={best['earth_departure_vinf_kms']:.2f},"
              f" peri={best['perihelion_AU']:.4f} AU,"
              f" return_vinf={best['earth_return_vinf_kms']:.2f}")
        print(f"    Moon deficit={best['moon_turn_deficit_deg']:.2f} deg,"
              f" Venus deficit={best['venus_turn_deficit_deg']:.2f} deg")
        print(f"    Score={best['score']:.2f}, Status={best['status']}")
    else:
        best = None

    # ---- Save ----
    top20 = candidates[:20] if candidates else []
    summary = {
        "ephemeris_source": venus_source,
        "num_candidates": len(candidates),
        "num_lambert_success": len(lambert_ok) + len(feasible),
        "num_feasible_ish": len(feasible),
        "grid": {
            "t0": t0_candidates,
            "moon_tof_days": moon_tof_days,
            "venus_tof_days": venus_tof_days,
            "return_tof_days": return_tof_days,
            "branches": ["prograde_short", "prograde_long"],
        },
        "best_candidate": best,
        "top20": top20,
        "note": (
            "Preliminary patched-conic chain exploration. "
            "Leg 1 (Earth->Moon) uses Earth-centred Lambert with Earth GM. "
            "Leg 2 (Moon->Venus) and Leg 3 (Venus->Earth) use heliocentric Lambert with Sun GM. "
            f"Venus source: {venus_source}. "
            "Flyby feasibility via required-turn vs available-turn at min periapsis. "
            "Not a full optimal-control multi-gravity-assist design."
        ),
    }

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    json_path = out_dir / "o4_multi_gravity_assist.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n  Saved: {json_path}")

    # CSV
    csv_path = out_dir / "o4_multi_gravity_assist.csv"
    if candidates:
        keys = [
            "t0_mjd", "moon_mjd", "venus_mjd", "return_mjd",
            "earth_departure_vinf_kms", "moon_turn_deficit_deg",
            "venus_turn_deficit_deg", "perihelion_AU",
            "earth_return_vinf_kms", "score", "status",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for c in candidates:
                w.writerow({k: c.get(k, "") for k in keys})
        print(f"  Saved: {csv_path}")

    # Plot
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(9, 6))
        if candidates:
            perihelions = [c["perihelion_AU"] for c in candidates]
            scores = [c["score"] for c in candidates]
            total_def = [
                c["moon_turn_deficit_deg"] + c["venus_turn_deficit_deg"]
                for c in candidates
            ]
            sc = ax.scatter(perihelions, scores, c=total_def,
                           cmap="RdYlGn_r", s=30, alpha=0.7,
                           edgecolors="k", linewidths=0.3)
            plt.colorbar(sc, ax=ax, label="Total turn deficit (deg)")
            if best:
                ax.scatter([best["perihelion_AU"]], [best["score"]],
                          c="gold", s=120, marker="*", edgecolors="k",
                          zorder=5, label="Best")
        ax.axvline(0.4, c="red", ls="--", alpha=0.5, label="Perihelion=0.4 AU")
        ax.set_xlabel("Perihelion (AU)")
        ax.set_ylabel("Score (lower=better)")
        ax.set_title("O4: Earth-Moon-Venus-Earth Chain Candidates")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        plot_path = out_dir / "o4_multi_gravity_assist_summary.png"
        fig.savefig(plot_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved: {plot_path}")
    except Exception as e:
        print(f"  Plot error: {e}")

    print(f"\n{'=' * 66}")
    print("O4: done (preliminary patched-conic chain exploration)")
    print(f"  Venus: {venus_source}")
    print(f"  Candidates: {len(candidates)}, Lambert OK: {len(lambert_ok)+len(feasible)},"
          f" Feasible-ish: {len(feasible)}")


if __name__ == "__main__":
    main()
