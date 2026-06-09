"""
generate_figure_manifest.py
===========================
Generates data/results/figure_manifest.json with all report-referenced figures.

This script does not replace any existing result.
"""

import json, os
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
RESULTS_DIR = _REPO / "data" / "results"
MANIFEST_PATH = RESULTS_DIR / "figure_manifest.json"

FIGURES = [
    {
        "file": "m8_trajectory.png",
        "report_label": "fig:trajectory",
        "section": "M8",
        "description": "Heliocentric complete orbit",
    },
    {
        "file": "m8_lunar_swingby.png",
        "report_label": "fig:lunar-swingby",
        "section": "M8",
        "description": "Moon-centered zoom",
    },
    {
        "file": "m8_launch_windows.png",
        "report_label": "fig:launch-windows",
        "section": "M8",
        "description": "Polar alignment radar",
    },
    {
        "file": "m8_sensitivity.png",
        "report_label": "fig:sensitivity",
        "section": "M8",
        "description": "Three-panel sensitivity",
    },
    {
        "file": "m8_horizons_residual.png",
        "report_label": "fig:residual",
        "section": "M3/M8",
        "description": "M3 daily residuals",
    },
    {
        "file": "m8_energy_drift.png",
        "report_label": "fig:energy-drift",
        "section": "M2/M8",
        "description": "Energy + AM conservation",
    },
    {
        "file": "m8_delta_v_launch_date.png",
        "report_label": "fig:delta-v-date",
        "section": "M6/M8",
        "description": "Window scan curves",
    },
    {
        "file": "m8_t0_rp_contour.png",
        "report_label": "fig:t0-rp-contour",
        "section": "M6/M8",
        "description": "Parameter contour",
    },
    {
        "file": "o3plus_vector_convergence.png",
        "report_label": "fig:o3plus-convergence",
        "section": "O3+",
        "description": "O3+ LM convergence after target-leak fix",
    },
    {
        "file": "m5_no_lunar_lambert_pareto.png",
        "report_label": "fig:m5-pareto",
        "section": "M5",
        "description": "No-lunar Lambert Pareto frontier",
    },
]

def main():
    manifest = []
    for fig in FIGURES:
        path = RESULTS_DIR / fig["file"]
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        manifest.append({
            **fig,
            "exists": exists,
            "size_bytes": size,
            "size_kb": round(size / 1024, 1) if exists else 0,
        })

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"[Manifest] Generated: {MANIFEST_PATH}")
    print(f"  Total figures: {len(manifest)}")
    print(f"  Present: {sum(1 for m in manifest if m['exists'])}")
    print(f"  Missing: {sum(1 for m in manifest if not m['exists'])}")

if __name__ == "__main__":
    main()
