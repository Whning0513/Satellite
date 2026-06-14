"""
m6_independent_window_search.py
===============================
Thin wrapper for the independent legal-window M6 search mode with
independent-output defaults.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
sys.path.insert(0, str(SRC))

RESULTS = REPO / "data" / "results"

from experiments.m6_complete_return_window_search import main as _shared_main


def main() -> int:
    argv = sys.argv[1:]
    if "--mode" not in argv:
        argv = ["--mode", "independent-legal-window", *argv]
    if "--output" not in argv:
        argv = ["--output", str(RESULTS / "m6_independent_window_search.json"), *argv]
    if "--csv-output" not in argv:
        argv = ["--csv-output", str(RESULTS / "m6_independent_window_search.csv"), *argv]
    sys.argv = [sys.argv[0], *argv]
    return _shared_main()


if __name__ == "__main__":
    raise SystemExit(main())
