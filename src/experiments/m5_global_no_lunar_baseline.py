"""
m5_global_no_lunar_baseline.py
===============================
M5 global no-lunar baseline diagnostic.

Broader search over launch dates and TOF values to support the
existing no-saving-ratio caveat. Does NOT replace the main M5 result.
"""

import json, os, sys, time, csv, itertools
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import GM_SUN, AU_KM
from units import km_to_au, day_to_sec
from lambert import solve_lambert_universal, orbital_elements_from_state
from trajectory import interpolate_state_at_mjd
from horizons import fetch_sem_vectors


def solve_leg(r1, r2, tof_days, mu=GM_SUN, prograde=True, long_way=False):
    tof_s = day_to_sec(tof_days)
    try:
        v1, v2, diag = solve_lambert_universal(
            r1, r2, tof_s, mu, prograde=prograde, long_way=long_way)
        if np.any(np.isnan(v1)) or np.any(np.isnan(v2)):
            return None
        return v1, v2
    except Exception:
        return None


def main():
    print("=" * 66)
    print("M5 global no-lunar baseline diagnostic")
    print("  (does NOT replace main M5 result)")
    print("=" * 66)

    body_data = fetch_sem_vectors(use_cache=True)
    jd_arr = np.array(body_data["Earth"]["jd_tdb"], dtype=float)
    mjd_arr = jd_arr - 2400000.5
    mjd_start = mjd_arr[0]
    mjd_end = mjd_arr[-1]

    # Lightweight grid
    t0_candidates = list(range(int(mjd_start), int(mjd_end) + 1, 10))
    # Add known M5/M6 key dates
    for extra in [61041.0, 61066.0, 61125.0, 61154.0, 61213.0]:
        if extra not in t0_candidates:
            t0_candidates.append(extra)
    t0_candidates = sorted(set(t0_candidates))

    tof_grid = list(range(180, 501, 20))  # 180-500 days, step 20
    branches = [(True, False), (True, True)]

    print(f"  t0: {len(t0_candidates)} dates ({t0_candidates[0]:.0f}-{t0_candidates[-1]:.0f})")
    print(f"  tof: {tof_grid[0]}-{tof_grid[-1]} days, step 20")
    print(f"  branches: {len(branches)}")

    candidates = []
    total_combos = len(t0_candidates) * len(tof_grid) * len(branches)
    print(f"  Total combos: ~{total_combos}")

    t0_start = time.time()
    for t0 in t0_candidates:
        try:
            rE0, vE0 = interpolate_state_at_mjd(body_data, "Earth", t0)
        except Exception:
            continue
        for tof in tof_grid:
            t1 = t0 + tof
            if t1 > mjd_end:
                continue
            try:
                rE1, vE1 = interpolate_state_at_mjd(body_data, "Earth", t1)
            except Exception:
                continue
            for pg, lw in branches:
                leg = solve_leg(rE0, rE1, tof, GM_SUN, prograde=pg, long_way=lw)
                if leg is None:
                    continue
                v1, v2 = leg
                dep_vinf = np.linalg.norm(v1 - vE0)
                ret_vinf = np.linalg.norm(v2 - vE1)
                a, e, rp, eps, h = orbital_elements_from_state(rE0, v1, GM_SUN)
                perihelion_au = rp / AU_KM
                peri_err = abs(perihelion_au - 0.3) / 0.3 * 100

                branch_label = f"{'pro' if pg else 'retro'}_{'long' if lw else 'short'}"

                peri_ok = peri_err <= 10
                ret_ok = ret_vinf <= 15
                dep_ok = dep_vinf <= 20

                cand = {
                    "t0_mjd": float(t0),
                    "return_mjd": float(t1),
                    "tof_days": float(tof),
                    "branch": branch_label,
                    "departure_vinf_kms": round(float(dep_vinf), 4),
                    "return_vinf_kms": float(round(ret_vinf, 4)),
                    "perihelion_AU": float(round(perihelion_au, 6)),
                    "perihelion_error_pct": float(round(peri_err, 2)),
                    "fair_baseline": bool(peri_ok and ret_ok and dep_ok),
                    "peri_unexcused": not(bool(peri_ok)),
                    "ret_unexcused": not(bool(ret_ok)),
                    "dep_unexcused": not(bool(dep_ok)),
                }
                candidates.append(cand)

    t_elapsed = time.time() - t0_start
    candidates.sort(key=lambda c: abs(c["perihelion_AU"] - 0.3))
    fair = [c for c in candidates if c["fair_baseline"]]

    print(f"\n  Elapsed: {t_elapsed:.0f}s")
    print(f"  Lambert successes: {len(candidates)}")
    print(f"  Fair baselines (peri≤10% + ret_vinf≤15 + dep_vinf≤20): {len(fair)}")

    best_peri = candidates[:5] if candidates else []
    best_ret = sorted(candidates, key=lambda c: c["return_vinf_kms"])[:5]
    best_bal = sorted(candidates, key=lambda c: (
        abs(c["perihelion_AU"] - 0.3) * 10 + max(0, c["return_vinf_kms"] - 15)
    ))[:5]

    if fair:
        conclusion = (
            f"{len(fair)} fair baselines found. "
            "This does NOT automatically change the M5 conclusion; "
            "manual review required."
        )
    else:
        conclusion = (
            "No fair baseline found in the extended grid. "
            "Supports the existing no-saving-ratio caveat."
        )

    print(f"\n  Conclusion: {conclusion}")

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    summary = {
        "task": "M5 global no-lunar baseline diagnostic",
        "does_not_replace_m5": True,
        "grid": {
            "t0": [float(t0_candidates[0]), float(t0_candidates[-1])],
            "tof_days": [tof_grid[0], tof_grid[-1]],
            "branches": ["prograde_short", "prograde_long"],
        },
        "num_candidates": len(candidates),
        "num_fair_baseline": len(fair),
        "best_by_perihelion": best_peri,
        "best_by_return_vinf": best_ret,
        "best_balanced": best_bal,
        "conclusion": conclusion,
    }

    jp = out_dir / "m5_global_no_lunar_baseline.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"JSON: {jp}")

    if candidates:
        csv_path = out_dir / "m5_global_no_lunar_baseline.csv"
        keys = ["t0_mjd", "return_mjd", "tof_days", "branch",
                "departure_vinf_kms", "return_vinf_kms",
                "perihelion_AU", "perihelion_error_pct", "fair_baseline"]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for c in candidates:
                w.writerow({k: c.get(k, "") for k in keys})
        print(f"CSV:  {csv_path}")

    # Pareto plot
    try:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(9, 6))
        if candidates:
            peri = [c["perihelion_AU"] for c in candidates]
            rv = [c["return_vinf_kms"] for c in candidates]
            sc = ax.scatter(peri, rv, c="steelblue", s=10, alpha=0.5)
            if fair:
                fp = [c for c in candidates if c["fair_baseline"]]
                ax.scatter([c["perihelion_AU"] for c in fp],
                          [c["return_vinf_kms"] for c in fp],
                          c="lime", s=40, marker="o", edgecolors="k",
                          label=f"Fair baseline ({len(fp)})")
        ax.axvline(0.27, c="red", ls="--", alpha=0.4, label="-10% rp")
        ax.axvline(0.33, c="red", ls="--", alpha=0.4, label="+10% rp")
        ax.axhline(15, c="green", ls="--", alpha=0.5, label="ret_vinf=15")
        ax.set_xlabel("perihelion (AU)"); ax.set_ylabel("return v_inf (km/s)")
        ax.set_title("M5 Global No-Lunar Baseline Diagnostic")
        ax.legend(fontsize=8); ax.grid(True, alpha=0.3)
        pp = out_dir / "m5_global_no_lunar_pareto.png"
        fig.savefig(pp, dpi=120, bbox_inches="tight"); plt.close()
        print(f"Plot: {pp}")
    except Exception as e:
        print(f"Plot error: {e}")

    print("=" * 66)


if __name__ == "__main__":
    main()
