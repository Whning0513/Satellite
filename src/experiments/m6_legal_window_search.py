"""
m6_legal_window_search.py
=========================
Formal legal-window entry point for M6 complete-return launch-window search.

This wrapper keeps the active M6 workflow on the 2026-constrained branch and
writes dedicated legal-window result filenames without changing the underlying
search engine.
"""

from __future__ import annotations

import argparse
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(_REPO / "src"))

from experiments.m6_complete_return_window_search import (
    RESULTS,
    _derived_legal_window_from_m5,
    _independent_direct_search,
    _write_outputs,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["derived-legal-window", "independent-legal-window"],
        default="derived-legal-window",
    )
    parser.add_argument("--output", type=str, default=str(RESULTS / "m6_legal_window_search.json"))
    parser.add_argument("--csv-output", type=str, default=str(RESULTS / "m6_legal_window_search.csv"))
    parser.add_argument("--t0-step-days", type=int, default=7)
    parser.add_argument("--top-k-seeds", type=int, default=8)
    parser.add_argument("--target-rp-au", type=float, default=0.3)
    parser.add_argument("--peri-tol-au", type=float, default=0.03)
    parser.add_argument("--earth-return-threshold-km", type=float, default=1.5e6)
    parser.add_argument("--return-vinf-brake-threshold-kms", type=float, default=15.0)
    parser.add_argument("--trajectory-dt-integrate-s", type=float, default=1800.0)
    parser.add_argument("--coarse-step-days", type=float, default=0.5)
    parser.add_argument("--coarse-dt-internal-s", type=float, default=3600.0)
    parser.add_argument("--refine-step-s", type=float, default=600.0)
    parser.add_argument("--nominal-window-half-width-days", type=float, default=150.0)
    parser.add_argument("--fallback-window-half-width-days", type=float, default=320.0)
    parser.add_argument("--refine-trajectory-dt-integrate-s", type=float, default=900.0)
    parser.add_argument("--refine-coarse-step-days", type=float, default=0.25)
    parser.add_argument("--refine-coarse-dt-internal-s", type=float, default=1800.0)
    parser.add_argument("--refine-refine-step-s", type=float, default=300.0)
    parser.add_argument("--refine-nominal-window-half-width-days", type=float, default=180.0)
    parser.add_argument("--refine-fallback-window-half-width-days", type=float, default=360.0)
    parser.add_argument("--max-extra-days", type=float, default=500.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print("=" * 66)
    print("M6 legal-window search")
    print("=" * 66)
    print(f"mode = {args.mode}")

    if args.mode == "derived-legal-window":
        payload = _derived_legal_window_from_m5()
    else:
        payload = _independent_direct_search(args)

    output_json = Path(args.output)
    output_csv = Path(args.csv_output)
    _write_outputs(payload, output_json, output_csv)

    print(f"Saved: {output_json}")
    print(f"Saved: {output_csv}")
    print(f"classification = {payload['classification']}")
    print(f"candidates evaluated = {payload['total_candidates_evaluated']}")
    print(f"valid complete returns = {payload['valid_complete_return_count']}")
    print(f"valid fair returns = {payload['valid_fair_return_count']}")
    if payload.get("best_valid_candidate"):
        best = payload["best_valid_candidate"]
        print(
            f"best valid: t0={best['t0_mjd']} side={best['side']} "
            f"r_m={best['r_m_km']} total={best['total_vinf_basis_kms']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
