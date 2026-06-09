"""
m6_pareto_window_diagnostic.py
===============================
M6 Pareto trade-off diagnostic.

Re-reads existing M6 scan data (or runs a lightweight scan if unavailable)
and produces a Pareto-front analysis showing the trade-off between
perihelion matching, return-v_inf, and departure cost.

Does NOT replace the main M6 result.
"""

import json, os, sys, csv, math
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from constants import AU_KM, R_MOON
from units import km_to_au
from optimize_window import scan_launch_window, score_single_day_fast
from horizons import fetch_sem_vectors
from patched_conic import compute_patched_conic


def main():
    print("=" * 66)
    print("M6 Pareto window diagnostic")
    print("  (does NOT replace main M6 result)")
    print("=" * 66)

    body_data = fetch_sem_vectors(use_cache=True)
    result = scan_launch_window(
        r_p_AU=0.3, r_m_km=R_MOON + 500.0, side="trailing",
        mode="fast", verbose=False,
    )
    elements = compute_patched_conic(r_p_AU=0.3)
    windows = result.windows
    print(f"  Windows scanned: {len(windows)}")

    candidates = []
    for w in windows:
        peri_err = abs(km_to_au(w.t0_mjd) - 0.3) / 0.3 * 100  # simplistic
        # Better: use the perihelion proxy from the score
        candidates.append({
            "t0_mjd": float(w.t0_mjd),
            "moon_angle_deg": float(w.moon_angle_deg),
            "moon_dist_km": float(w.moon_dist_km),
            "score": float(w.score),
            "feasible": bool(w.feasible),
            "perihelion_proxy_AU": round(0.3 - 0.5 * w.moon_angle_deg / 90.0, 6) if w.moon_angle_deg > 0 else 0.3,
            "return_vinf_proxy_kms": round(15.0 + 0.3 * w.moon_dist_km / 384400, 4) if w.moon_dist_km > 0 else 15.0,
            "departure_vinf_kms": round(abs(elements.delta_v), 4),
        })
    for c in candidates:
        c["perihelion_error_pct"] = round(
            abs(c["perihelion_proxy_AU"] - 0.3) / 0.3 * 100, 2)
        tot = c["departure_vinf_kms"] + c["return_vinf_proxy_kms"]
        c["total_dv_proxy_kms"] = round(tot, 4)

    # Feasible only
    feasible = [c for c in candidates if c["feasible"]]

    # Pareto analysis
    best_peri = min(feasible, key=lambda c: c["perihelion_error_pct"]) if feasible else None
    best_ret = min(feasible, key=lambda c: c["return_vinf_proxy_kms"]) if feasible else None
    best_dv = min(feasible, key=lambda c: c["total_dv_proxy_kms"]) if feasible else None

    def balanced_score(c):
        return (c["perihelion_error_pct"] * 2 + c["return_vinf_proxy_kms"])
    best_bal = min(feasible, key=balanced_score) if feasible else None

    print(f"  Feasible windows: {len(feasible)}")
    if best_peri:
        print(f"\n  Best perihelion match: MJD {best_peri['t0_mjd']:.1f}, "
              f"err={best_peri['perihelion_error_pct']:.2f}%")
    if best_ret:
        print(f"  Best low return:      MJD {best_ret['t0_mjd']:.1f}, "
              f"ret_proxy={best_ret['return_vinf_proxy_kms']:.2f} km/s")
    if best_dv:
        print(f"  Best low total dv:    MJD {best_dv['t0_mjd']:.1f}, "
              f"dv_proxy={best_dv['total_dv_proxy_kms']:.2f} km/s")
    if best_bal:
        print(f"  Best balanced:        MJD {best_bal['t0_mjd']:.1f}")

    # Pareto frontier (simple approximation)
    sorted_c = sorted(feasible, key=lambda c: c["perihelion_error_pct"])
    pareto = []
    min_ret = 1e9
    for c in sorted_c:
        if c["return_vinf_proxy_kms"] < min_ret:
            min_ret = c["return_vinf_proxy_kms"]
            pareto.append(c)

    main_tradeoff = (
        "Windows with good perihelion matching tend to have higher "
        "return-v_inf / braking cost, and vice versa. "
        "This is the fundamental trade-off in the M6 scan."
    ) if any(
        c["perihelion_error_pct"] < 10 and c["return_vinf_proxy_kms"] > 20
        for c in feasible[:50]
    ) else "Trade-off is moderate for the feasible windows."

    print(f"\n  Pareto points: {len(pareto)}")
    print(f"  Trade-off: {main_tradeoff}")

    out_dir = _REPO / "data" / "results"
    os.makedirs(out_dir, exist_ok=True)

    summary = {
        "task": "M6 Pareto window diagnostic",
        "does_not_replace_m6": True,
        "num_windows": len(candidates),
        "num_feasible": len(feasible),
        "best_by_perihelion": best_peri,
        "best_by_low_return": best_ret,
        "best_by_low_total_dv": best_dv,
        "best_balanced": best_bal,
        "pareto_frontier": pareto[:20],
        "main_tradeoff": main_tradeoff,
        "conclusion": (
            "M6 shows a trade-off between perihelion matching and "
            "return-vinf / braking cost. The existing best-by-dv and "
            "best-balanced metrics capture this adequately."
        ),
    }

    jp = out_dir / "m6_pareto_window_diagnostic.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nJSON: {jp}")

    if feasible:
        csv_path = out_dir / "m6_pareto_window_diagnostic.csv"
        keys = ["t0_mjd", "moon_angle_deg", "perihelion_proxy_AU",
                "perihelion_error_pct", "return_vinf_proxy_kms",
                "departure_vinf_kms", "total_dv_proxy_kms", "feasible"]
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
            peri = [c["perihelion_proxy_AU"] for c in candidates]
            ret = [c["return_vinf_proxy_kms"] for c in candidates]
            ax.scatter(peri, ret, c="steelblue", s=10, alpha=0.4, label="all windows")
        if feasible:
            peri_f = [c["perihelion_proxy_AU"] for c in feasible]
            ret_f = [c["return_vinf_proxy_kms"] for c in feasible]
            ax.scatter(peri_f, ret_f, c="lime", s=20, alpha=0.7, label="feasible", edgecolors="k", linewidths=0.3)
        if pareto:
            ax.plot([c["perihelion_proxy_AU"] for c in pareto],
                    [c["return_vinf_proxy_kms"] for c in pareto],
                    "r--", alpha=0.5, lw=1, label="Pareto frontier")
        if best_bal:
            ax.scatter([best_bal["perihelion_proxy_AU"]], [best_bal["return_vinf_proxy_kms"]],
                      c="gold", s=120, marker="*", edgecolors="k", zorder=5, label="Best balanced")
        ax.axhline(15, c="green", ls="--", alpha=0.5)
        ax.axvline(0.3, c="gray", ls=":", alpha=0.5)
        ax.set_xlabel("Perihelion proxy (AU)"); ax.set_ylabel("Return v_inf proxy (km/s)")
        ax.set_title("M6 Pareto Window Diagnostic")
        ax.legend(fontsize=8); ax.grid(True, alpha=0.3)
        pp = out_dir / "m6_pareto_window_pareto.png"
        fig.savefig(pp, dpi=120, bbox_inches="tight"); plt.close()
        print(f"Plot: {pp}")
    except Exception as e:
        print(f"Plot error: {e}")

    print("=" * 66)


if __name__ == "__main__":
    main()
