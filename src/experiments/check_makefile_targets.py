"""
check_makefile_targets.py
=========================
Validate that required engineering targets exist in the Makefile.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MAKEFILE = REPO / "Makefile"

REQUIRED_TARGETS = {
    "m1": True,
    "m2": True,
    "m3-hierarchy": True,
    "m4": True,
    "repair-m5-real": True,
    "complete-lunar-return-search": True,
    "m5-lunar-best-fixed-date-compare": True,
    "m5-t61037-deep-compare": True,
    "m5-same-window-pareto": True,
    "m6-complete-window-search": True,
    "m6-independent-spotcheck": True,
    "m6-deep-audit": True,
    "check-m6-return-semantics": True,
    "m3-deep-audit": True,
    "check-m3-horizons-semantics": True,
    "check-invalidated-results": True,
    "return-semantics-test": True,
    "check-m7-return-semantics": True,
    "figure-manifest": True,
    "audit": True,
}

DOC_FILES = [
    "README.md",
    "FINAL_AUDIT.md",
    "PROJECT_FINAL_HANDOFF.md",
    "IMPACT_ANALYSIS.md",
    "M5_REAL_REPAIR_AUDIT.md",
    "M3_M6_ACTUAL_REPAIR_AUDIT.md",
]


def parse_targets(text: str) -> set[str]:
    targets: set[str] = set()
    for line in text.splitlines():
        if line.startswith("\t") or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+):", line)
        if match:
            targets.add(match.group(1))
    return targets


def main() -> int:
    text = MAKEFILE.read_text(encoding="utf-8")
    targets = parse_targets(text)

    missing_required = []
    print("=== Makefile target check ===")
    for target, required in REQUIRED_TARGETS.items():
        if target in targets:
            print(f"[OK] target present: {target}")
        else:
            print(f"missing target: {target}")
            print(f"is it required: {required}")
            print("action: create the target or update referencing docs")
            if required:
                missing_required.append(target)

    referenced_but_missing = set()
    for rel in DOC_FILES:
        path = REPO / rel
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        for target in REQUIRED_TARGETS:
            if f"`make {target}`" in content and target not in targets:
                referenced_but_missing.add(target)

    if referenced_but_missing:
        for target in sorted(referenced_but_missing):
            print(f"obsolete referenced target: {target}")
            print("is it required: True")
            print("action: fix Makefile or update engineering docs")

    if missing_required:
        print(f"\nFAIL: missing required targets: {missing_required}")
        return 1

    print("\nAll required targets exist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
