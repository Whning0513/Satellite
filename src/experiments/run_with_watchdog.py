"""
run_with_watchdog.py
====================
Lightweight external watchdog for long-running numerical jobs.

Usage examples:
  python src/experiments/run_with_watchdog.py --interval-min 10 -- \
      python src/experiments/m5_legal_window_search.py

  python src/experiments/run_with_watchdog.py --interval-min 10 -- \
      make m7-mc-full

Behavior:
  - launches the target command as a child process
  - prints a heartbeat every N minutes
  - writes a watchdog log under data/results/
  - if the child exits with non-zero status, emits a visible alert
  - on Windows, tries to show a MessageBox popup
  - on Linux, tries notify-send if available
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "data" / "results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a long job under an external watchdog."
    )
    parser.add_argument(
        "--interval-min",
        type=float,
        default=10.0,
        help="Heartbeat interval in minutes. Default: 10",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="numerical-job",
        help="Short label shown in heartbeats and alerts.",
    )
    parser.add_argument(
        "--log",
        type=str,
        default="",
        help="Optional explicit watchdog log path.",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to run. Put '--' before the command.",
    )
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("missing child command; use '-- <command ...>'")
    return args


def _timestamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _default_log_path(name: str) -> Path:
    safe_name = "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in name)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return RESULTS / f"watchdog_{safe_name}_{stamp}.log"


def _write_log(handle, message: str) -> None:
    line = f"[{_timestamp()}] {message}"
    print(line, flush=True)
    handle.write(line + "\n")
    handle.flush()


def _emit_alert(title: str, message: str) -> None:
    sys.stderr.write("\a")
    sys.stderr.flush()

    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
            return
        except Exception:
            pass
    else:
        notify_send = shutil.which("notify-send")
        if notify_send:
            try:
                subprocess.run(
                    [notify_send, title, message],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            except Exception:
                pass

    print(f"ALERT: {title}: {message}", file=sys.stderr, flush=True)


def main() -> int:
    args = parse_args()
    interval_sec = max(30.0, float(args.interval_min) * 60.0)
    RESULTS.mkdir(parents=True, exist_ok=True)
    log_path = Path(args.log) if args.log else _default_log_path(args.name)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with log_path.open("w", encoding="utf-8") as log_handle:
        _write_log(log_handle, f"watchdog start name={args.name}")
        _write_log(log_handle, f"cwd={REPO}")
        _write_log(log_handle, f"command={' '.join(args.command)}")
        _write_log(log_handle, f"heartbeat_interval_min={args.interval_min}")

        started = time.time()
        proc = subprocess.Popen(args.command, cwd=str(REPO))
        _write_log(log_handle, f"child_pid={proc.pid}")

        next_heartbeat = time.time() + interval_sec
        while True:
            code = proc.poll()
            now = time.time()
            if code is not None:
                elapsed = now - started
                _write_log(
                    log_handle,
                    f"child_exit_code={code} elapsed_sec={elapsed:.1f}",
                )
                if code != 0:
                    _emit_alert(
                        f"Watchdog: {args.name} failed",
                        f"Child process exited with code {code}. "
                        f"See log: {log_path}",
                    )
                else:
                    print(
                        f"[{_timestamp()}] watchdog finished cleanly; log={log_path}",
                        flush=True,
                    )
                return int(code)

            if now >= next_heartbeat:
                elapsed = now - started
                _write_log(
                    log_handle,
                    f"heartbeat child_pid={proc.pid} alive elapsed_sec={elapsed:.1f}",
                )
                next_heartbeat = now + interval_sec

            time.sleep(5.0)


if __name__ == "__main__":
    raise SystemExit(main())
