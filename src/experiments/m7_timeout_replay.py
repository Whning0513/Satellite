"""
m7_timeout_replay.py
====================
Replay selected timeout samples from saved M7 Monte Carlo sample rows.

This is intended as a follow-on high-accuracy diagnostic after a full run
that was produced with --save-sample-rows.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
RESULTS = REPO / "data" / "results"
sys.path.insert(0, str(SRC))

from experiments.m7_extended_monte_carlo import _run_pool


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("results")
    if not isinstance(rows, list):
        raise ValueError(f"{path} missing results list")
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=str, default=str(RESULTS / "m7_extended_monte_carlo_samples.json"))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--max-runtime-sec", type=float, default=3600.0)
    parser.add_argument("--max-runtime-per-sample-sec", type=float, default=300.0)
    parser.add_argument("--output", type=str, default=str(RESULTS / "m7_timeout_replay.json"))
    parser.add_argument("--csv-output", type=str, default=str(RESULTS / "m7_timeout_replay.csv"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_rows = _load_rows(Path(args.samples))
    timeout_rows = [row for row in source_rows if row.get("classification") == "TIMEOUT_NO_FORMAL_RESULT"]
    selected = timeout_rows[: max(0, int(args.limit))]

    replay_samples = []
    for row in selected:
        replay_samples.append(
            {
                "sample_id": row["sample_id"],
                "t0_mjd": float(row["t0_mjd"]),
                "r_m_km": float(row["r_m_km"]),
                "r_p_au": float(row["rp_target_au"]),
                "side": row.get("side", "trailing"),
                "nominal_return_mjd": float(row["nominal_return_mjd"]),
                "max_runtime_per_sample_sec": float(args.max_runtime_per_sample_sec),
            }
        )

    replay_results = _run_pool(
        replay_samples,
        max_workers=max(1, int(args.max_workers)),
        max_runtime_sec=float(args.max_runtime_sec),
    ) if replay_samples else []

    payload = {
        "task": "M7 timeout replay",
        "source_samples_file": str(Path(args.samples).relative_to(REPO)).replace("\\", "/"),
        "requested_limit": int(args.limit),
        "selected_timeout_samples": len(replay_samples),
        "replay_max_runtime_sec": float(args.max_runtime_sec),
        "replay_max_runtime_per_sample_sec": float(args.max_runtime_per_sample_sec),
        "results": replay_results,
    }

    out_json = Path(args.output)
    out_csv = Path(args.csv_output)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    if replay_results:
        with out_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(replay_results[0].keys()))
            writer.writeheader()
            writer.writerows(replay_results)

    print(f"Saved: {out_json}")
    if replay_results:
        print(f"Saved: {out_csv}")
    print(f"selected_timeout_samples = {len(replay_samples)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
