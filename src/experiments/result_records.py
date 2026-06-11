"""
result_records.py
=================
Shared structured result helpers for experiment/audit outputs.

This module is intentionally small and standard-library-only so new
audits can emit one consistent JSON/CSV shape without forcing a full
repo migration in one step.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass
class AuditRecord:
    module: str
    quantity: str
    project_value: Any
    independent_check_value: Any
    relative_error: float | None
    unit: str
    frame: str
    event: str
    status: str
    classification: str
    action: str
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def write_csv(path: Path, records: Iterable[AuditRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = list(records)
    fieldnames = list(AuditRecord.__dataclass_fields__.keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_dict())
