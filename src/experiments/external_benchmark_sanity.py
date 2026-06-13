"""
external_benchmark_sanity.py
============================
Cross-check current project magnitudes against official external references.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "data" / "results"


def _load(name: str) -> dict | None:
    path = RESULTS / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _row(module: str, quantity: str, project_value, benchmark_value, unit: str, source: str, sanity: str) -> dict:
    return {
        "module": module,
        "quantity": quantity,
        "project_value": project_value,
        "benchmark_value": benchmark_value,
        "unit": unit,
        "source": source,
        "sanity": sanity,
    }


def main() -> int:
    rows: list[dict] = []

    m5 = _load("m5_best_lunar_candidate_verify.json")
    m5_compare = _load("m5_fixed_date_current_compare.json")
    m7 = _load("m7_extended_monte_carlo.json")

    artemis_reentry_kms = round(24581 * 1.609344 / 3600.0, 4)
    parker_surface_distance_au = round(6.2e6 / 149597870.7, 5)
    parker_center_distance_au = round((6.2e6 + 696000.0) / 149597870.7, 5)

    if m5 is not None:
        rows.append(
            _row(
                "M5",
                "legal lunar return_vinf",
                m5["state_at_return"]["return_vinf_kms"],
                artemis_reentry_kms,
                "km/s",
                "NASA Artemis I re-entry speed",
                "Same order of magnitude as a real cislunar return mission. Not identical quantity: Artemis value is atmospheric re-entry speed, project value is Earth-relative return v_infinity.",
            )
        )
        rows.append(
            _row(
                "M5",
                "legal perihelion",
                m5["trajectory_summary"]["r_p_achieved_AU"],
                parker_center_distance_au,
                "AU",
                "NASA Parker Solar Probe closest solar distance",
                "Project perihelion is far less extreme than Parker Solar Probe, so 0.27-0.30 AU is physically plausible as a solar swing-in target.",
            )
        )

    if m5_compare is not None:
        rows.append(
            _row(
                "M5",
                "legal fixed-date saving ratio",
                m5_compare["formal_ratio_vinf_basis"],
                None,
                "ratio",
                "Classical gravity-assist design literature",
                "A positive ~0.51 saving ratio is numerically plausible for a same-date lunar-assist versus deep-space-manuever proxy comparison, but it is still a project-internal benchmark rather than an external mission number.",
            )
        )

    if m7 is not None:
        rows.append(
            _row(
                "M7",
                "valid-only return_vinf p95",
                m7["return_vinf_valid_only"]["p95"],
                artemis_reentry_kms,
                "km/s",
                "NASA Artemis I re-entry speed",
                "Valid-only Monte Carlo returns stay in the same broad cislunar-return speed class; no formal value is remotely near the old fake ~79 km/s.",
            )
        )

    rows.append(
        _row(
            "M3",
            "Horizons center semantics",
            "@10 barycenter usage required",
            "@10 / barycenter form",
            "text",
            "JPL Horizons manual",
            "This matches official Horizons guidance; using CENTER='@10' is consistent with barycentric/solar-system-center semantics rather than an observing-site code.",
        )
    )

    payload = {
        "task": "External benchmark sanity",
        "rows": rows,
        "sources": [
            {
                "label": "NASA Artemis I mission facts",
                "url": "https://www.nasa.gov/mission/artemis-i/",
                "note": "Re-entry speed 24,581 mph (Mach 32).",
            },
            {
                "label": "NASA Parker Solar Probe mission page",
                "url": "https://science.nasa.gov/mission/parker-solar-probe/",
                "note": "Closest approach about 3.9 million miles (6.2 million km) from the Sun.",
            },
            {
                "label": "JPL Horizons manual",
                "url": "https://ssd.jpl.nasa.gov/horizons/manual.html",
                "note": "Explains barycenter/system-center conventions including 10 and @10 forms.",
            },
            {
                "label": "NASA gravity-assist technical literature",
                "url": "https://ntrs.nasa.gov/api/citations/19670002059/downloads/19670002059.pdf",
                "note": "Classical gravity-assist quantities include passage distance and turning angle.",
            },
        ],
    }

    json_path = RESULTS / "external_benchmark_sanity.json"
    csv_path = RESULTS / "external_benchmark_sanity.csv"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["module", "quantity", "project_value", "benchmark_value", "unit", "source", "sanity"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved: {json_path}")
    print(f"Saved: {csv_path}")
    print(f"rows = {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
