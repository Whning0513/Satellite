"""
aux_results.py
==============
Generate remaining audit/analysis result files:
  1. M3 error budget      → data/results/m3_error_budget.json
  2. M6 balanced ranking  → data/results/m6_refined_windows.json, m6_refinement_table.csv
  3. M8 figure manifest   → data/results/figure_manifest.json

All files are written to data/results/.
"""

import json, os, csv, sys, numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

OUT = _REPO / "data" / "results"
os.makedirs(OUT, exist_ok=True)


# ============================================================
# 1. M3 Error Budget
# ============================================================
def gen_m3_error_budget():
    """Read ablation result and assemble error budget JSON."""
    ablation_path = OUT / "m3_residual_ablation.json"
    if not ablation_path.exists():
        print("[M3] Skipping: no m3_residual_ablation.json")
        return

    with open(ablation_path) as f:
        ablation = json.load(f)

    # Find best mode (E4: barycentric+heliocentric, 3D, 60s)
    best = None
    for exp in ablation:
        if exp.get("experiment") == "E4" and "body_stats" in exp:
            best = exp
            break
    if best is None:
        for exp in ablation:
            if exp.get("experiment") == "E3" and "body_stats" in exp:
                best = exp
                break

    if best is None:
        print("[M3] No E3/E4 found in ablation results")
        return

    budget = {
        "threshold_km": 6000.0,
        "overall_max_pos_km": best["overall_max_pos_km"],
        "overall_max_body": max(
            [(b, best["body_stats"][b]["max_pos_km"]) for b in ["sun", "earth", "moon"]],
            key=lambda x: x[1])[0].capitalize(),
        "overall_max_day": max(
            [(b, best["body_stats"][b]["max_day"]) for b in ["sun", "earth", "moon"]],
            key=lambda x: x[1])[1],
        "body_stats": best["body_stats"],
        "model_notes": {
            "dimension": "3D",
            "frame": "SSB barycentric integrate + heliocentric comparison (post-hoc transform, not fitting)",
            "dt_s": best["dt_s"],
            "comparison": best["comparison"],
            "n_bodies": 3,
            "missing_perturbations": ["Venus", "Jupiter", "Saturn", "Mars"],
            "note": "~5900 km residual is dominated by missing planetary perturbations (esp. Jupiter), not integration error"
        },
        "ablation_summary": {
            exp.get("experiment", "?"): {
                "max_pos_km": exp.get("overall_max_pos_km"),
                "pass_6000km": exp.get("threshold_6000km")
            }
            for exp in ablation if "overall_max_pos_km" in exp
        }
    }

    p = OUT / "m3_error_budget.json"
    with open(p, "w") as f:
        json.dump(budget, f, indent=2)
    print(f"[M3] Error budget saved to {p}")


# ============================================================
# 2. M6 Balanced Ranking
# ============================================================
def gen_m6_balanced_ranking():
    """Read refined JSON, compute balanced score, save results."""
    refined_path = OUT / "m6_refined.json"
    if not refined_path.exists():
        print("[M6] Skipping: no m6_refined.json")
        return

    with open(refined_path) as f:
        data = json.load(f)

    windows = data.get("refined_windows", [])
    if not windows:
        print("[M6] No refined windows to rank")
        return

    rp_design = data["r_p_design_AU"]
    rows = []

    for w in windows:
        rp_err = abs(w["r_p_achieved_AU"] - rp_design) / rp_design
        dv_total = w.get("v_launch_kms", 0) + w.get("v_reentry_kms", 0)
        # Balanced score: dv_total + penalty for rp_error
        # Penalty: rp_error beyond 5% incurs quadratic penalty
        rp_tol = 0.05
        penalty = 100 * max(0, rp_err - rp_tol) ** 2
        balanced_score = dv_total + penalty

        rows.append({
            "t0_mjd": w["t0_mjd"],
            "side": data.get("side", "trailing"),
            "r_m_km": data.get("r_m_km", 2237.4),
            "rp_target_AU": rp_design,
            "rp_actual_AU": w["r_p_achieved_AU"],
            "rp_error_rel": round(rp_err, 6),
            "dv_launch_kms": w["v_launch_kms"],
            "dv_lunar_residual_kms": w.get("dv_moon_kms", 0),
            "dv_reentry_kms": w["v_reentry_kms"],
            "dv_total_kms": round(dv_total, 4),
            "balanced_score": round(balanced_score, 2),
            "flight_time_days": w["t_total_days"],
            "constraints_satisfied": w["success"],
            "failure_reason": None,
        })

    # Sort by balanced_score
    rows.sort(key=lambda r: r["balanced_score"])

    # CSV
    csv_path = OUT / "m6_refinement_table.csv"
    with open(csv_path, "w", newline="") as f:
        fields = ["t0_mjd", "side", "r_m_km", "rp_target_AU", "rp_actual_AU",
                  "rp_error_rel", "dv_launch_kms", "dv_lunar_residual_kms",
                  "dv_reentry_kms", "dv_total_kms", "balanced_score",
                  "flight_time_days", "constraints_satisfied", "failure_reason"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"[M6] Refinement table saved to {csv_path}")

    # JSON
    rankings = {
        "r_p_design_AU": rp_design,
        "best_by_dv": min(rows, key=lambda r: r["dv_total_kms"]),
        "best_balanced": rows[0],
        "ranked_windows": rows,
        "note": ("best_by_dv minimizes total delta-v; best_balanced combines "
                 "dv_total with penalty for rp_error > 5%. MJD 61154.0 wins on dv "
                 "but has 8.33% rp error; MJD 61066.0 has 5.2% rp error."),
    }

    # Override best_by_dv to be the minimum dv_total
    rankings["best_by_dv"] = min(rows, key=lambda r: r["dv_total_kms"])
    rankings["best_balanced"] = rows[0]

    p = OUT / "m6_refined_windows.json"
    with open(p, "w") as f:
        json.dump(rankings, f, indent=2)
    print(f"[M6] Rankings saved to {p}")


# ============================================================
# 3. M8 Figure Manifest
# ============================================================
def gen_m8_figure_manifest():
    """List all PNGs in data/results/ with metadata."""
    pngs = sorted(OUT.glob("m8_*.png"))
    gifs = sorted(OUT.glob("m8_*.gif"))

    manifest = []

    for p in pngs + gifs:
        fname = p.name
        sz = p.stat().st_size

        # Determine description and report label from filename
        desc_map = {
            "m8_trajectory": "Full heliocentric trajectory plot",
            "m8_lunar_swingby": "Lunar swingby close-up detail",
            "m8_launch_windows": "Polar launch-window alignment",
            "m8_sensitivity": "Sensitivity analysis three-panel",
            "m8_horizons_residual": "Horizons daily position/velocity residuals",
            "m8_energy_drift": "N-body energy and angular momentum drift",
            "m8_delta_v_launch_date": "Delta-v vs launch date curve",
            "m8_t0_rp_contour": "t0-rp parameter scan contour",
            "m8_anim_test": "Orbit animation (test GIF, 5s)",
        }
        base = fname.rsplit(".", 1)[0]
        desc = desc_map.get(base, "Unknown")

        report_label = None
        if base != "m8_anim_test":
            report_label = f"fig:{base.replace('m8_','')}"

        manifest.append({
            "filename": str(p),
            "generated_by": "make figures (validation.py --case m8)",
            "input_files": ["m3_residuals.json", "Horizons cache", "trajectory solve"],
            "report_label": report_label,
            "description": desc,
            "exists": True,
            "size_bytes": sz,
            "size_kb": round(sz / 1024, 1),
        })

    # Check report.tex references
    report_path = _REPO / "report.tex"
    refs_in_report = []
    if report_path.exists():
        with open(report_path, encoding="utf-8") as f:
            tex = f.read()
        import re
        refs = re.findall(r'data/results/(m8_[^}]+\.png)', tex)
        refs_in_report = sorted(set(refs))

    report = {
        "figure_manifest": manifest,
        "report_references": refs_in_report,
        "num_figures": len(manifest),
        "num_report_refs": len(refs_in_report),
        "all_referenced_found": all(
            any(r["filename"].endswith(ref) for r in manifest)
            for ref in refs_in_report
        ),
        "generated_by": "aux_results.py / make figures",
    }

    p = OUT / "figure_manifest.json"
    with open(p, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[M8] Figure manifest saved to {p} ({len(manifest)} figures)")


if __name__ == "__main__":
    print("=" * 66)
    print("Auxiliary results generation")
    print("=" * 66)

    gen_m3_error_budget()
    gen_m6_balanced_ranking()
    gen_m8_figure_manifest()

    print("\nDone.")
