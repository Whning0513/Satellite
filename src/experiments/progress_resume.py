"""
progress_resume.py
==================
Shared checkpoint/resume and terminal progress helpers for long-running jobs.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Callable


def _now() -> float:
    return time.perf_counter()


def format_seconds(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(seconds):
        return "--:--:--"
    seconds_i = max(0, int(round(seconds)))
    hours, rem = divmod(seconds_i, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class ProgressBar:
    def __init__(self, total: int, *, label: str, width: int = 28) -> None:
        self.total = max(0, int(total))
        self.label = label
        self.width = max(10, int(width))
        self.started = _now()
        self.last_render = 0.0
        self.last_message_len = 0

    def update(self, done: int, *, extra: str = "") -> None:
        now = _now()
        if done < self.total and now - self.last_render < 0.4:
            return
        self.last_render = now
        elapsed = now - self.started
        ratio = 1.0 if self.total == 0 else min(1.0, max(0.0, done / self.total))
        filled = int(round(ratio * self.width))
        bar = "#" * filled + "-" * (self.width - filled)
        rate = done / elapsed if elapsed > 1e-9 else 0.0
        eta = None if rate <= 1e-9 or done <= 0 else (self.total - done) / rate
        msg = (
            f"\r[{bar}] {done}/{self.total} "
            f"{ratio * 100:5.1f}% elapsed={format_seconds(elapsed)} "
            f"eta={format_seconds(eta)} {self.label}"
        )
        if extra:
            msg += f" | {extra}"
        pad = max(0, self.last_message_len - len(msg))
        sys.stdout.write(msg + (" " * pad))
        sys.stdout.flush()
        self.last_message_len = len(msg)

    def finish(self, *, extra: str = "") -> None:
        self.update(self.total, extra=extra)
        sys.stdout.write("\n")
        sys.stdout.flush()
        self.last_message_len = 0


class JsonlCheckpoint:
    def __init__(
        self,
        path: Path,
        *,
        key_fn: Callable[[dict[str, Any]], str],
    ) -> None:
        self.path = path
        self.key_fn = key_fn
        self.rows_by_key: dict[str, dict[str, Any]] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    self.rows_by_key[self.key_fn(row)] = row

    def __len__(self) -> int:
        return len(self.rows_by_key)

    def has_key(self, key: str) -> bool:
        return key in self.rows_by_key

    def get_rows(self) -> list[dict[str, Any]]:
        return list(self.rows_by_key.values())

    def append(self, row: dict[str, Any]) -> None:
        key = self.key_fn(row)
        self.rows_by_key[key] = row
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def compact(self) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            for row in self.get_rows():
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

