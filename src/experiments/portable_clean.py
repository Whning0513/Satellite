"""
portable_clean.py
=================
Cross-platform cleanup for cache/build/result artifacts.
"""

from __future__ import annotations

import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

LATEX_ARTIFACTS = [
    "report.aux",
    "report.log",
    "report.out",
    "report.toc",
    "report.pdf",
]


def safe_unlink(path: Path) -> None:
    if path.exists() and path.is_file():
        path.unlink()


def main() -> int:
    for path in REPO.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)

    for path in REPO.rglob("*.pyc"):
        safe_unlink(path)

    for rel in LATEX_ARTIFACTS:
        safe_unlink(REPO / rel)

    results = REPO / "data" / "results"
    if results.exists():
        for pattern in ("*.png", "*.gif", "*.json"):
            for path in results.glob(pattern):
                safe_unlink(path)

    print("Cleaned __pycache__, .pyc, LaTeX artifacts, and data/results/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
