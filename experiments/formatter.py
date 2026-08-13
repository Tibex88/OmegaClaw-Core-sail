"""Pretty per-run log writer + JSONL snapshot capture.

The goal is a human-readable timeline that surfaces what OmegaSen actually
did — snapshots, chosen actions, lifecycle events, target detection — with
noisy websocket/HTTP debug output silenced.
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, TextIO

# Loggers we want to shut off for the pretty file (they're still available if
# a scenario opts into --verbose for stdout).
_NOISY_LOGGERS = (
    "websockets",
    "websockets.client",
    "websockets.server",
    "httpx",
    "httpx2",
    "httpcore",
    "httpcore.http11",
    "httpcore.connection",
    "httpcore2",
    "httpcore2.http11",
    "httpcore2.connection",
    "openai",
    "openai._base_client",
    "asyncio",
)


def silence_noise() -> None:
    """Set noisy library loggers to WARNING so pretty logs stay readable."""
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


class PrettyRunWriter:
    """Owns the pretty run.log file and a companion snapshots.jsonl for replay."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = run_dir / "run.log"
        self.jsonl_path = run_dir / "snapshots.jsonl"
        self.metrics_path = run_dir / "metrics.json"
        self._log_fh: Optional[TextIO] = None
        self._jsonl_fh: Optional[TextIO] = None
        self._start_monotonic: Optional[float] = None
        self.snapshot_count = 0

    def __enter__(self) -> "PrettyRunWriter":
        self._log_fh = self.log_path.open("w", buffering=1)  # line-buffered
        self._jsonl_fh = self.jsonl_path.open("w", buffering=1)
        self._start_monotonic = time.monotonic()
        return self

    def __exit__(self, *exc: Any) -> None:
        for fh in (self._log_fh, self._jsonl_fh):
            if fh is not None:
                fh.close()
        self._log_fh = None
        self._jsonl_fh = None

    def _elapsed(self) -> float:
        return 0.0 if self._start_monotonic is None else time.monotonic() - self._start_monotonic

    def _write(self, line: str) -> None:
        if self._log_fh is None:
            return
        self._log_fh.write(line.rstrip() + "\n")

    def header(self, name: str, description: str, config: Dict[str, Any]) -> None:
        self._write(f"== {name}  ({datetime.now(timezone.utc).isoformat(timespec='seconds')}) ==")
        if description:
            self._write(f"    {description}")
        self._write("config")
        for k, v in config.items():
            self._write(f"    {k:<10}: {v}")
        self._write("")

    def connect(self, endpoint: str, ok: bool, milliseconds: Optional[float] = None) -> None:
        status = "OK" if ok else "FAILED"
        ms = f"  in {milliseconds:.0f}ms" if milliseconds is not None else ""
        self._write(f"connect  {endpoint}  {status}{ms}")

    def snapshot(self, snapshot: Any) -> None:
        self.snapshot_count += 1
        pos = snapshot.player_status.get("Position")
        fwd = snapshot.player_status.get("Forward")
        actions = snapshot.player_actions
        n_visible = len(snapshot.player_perception.get("VisibleEntities") or [])
        primitives = ",".join(actions.primitives)
        move_to = len(actions.move_to_targets)
        self._write(
            f"t+{self._elapsed():05.2f}  snapshot #{self.snapshot_count:<3}  "
            f"pos={_fmt_vec(pos)}  fwd={_fmt_vec(fwd)}  visible={n_visible}"
        )
        self._write(f"                       primitives=[{primitives}]  MoveTo={move_to} targets")
        if self._jsonl_fh is not None:
            self._jsonl_fh.write(json.dumps({
                "t": round(self._elapsed(), 3),
                "kind": "snapshot",
                "payload": snapshot.raw,
            }) + "\n")

    def action_out(self, action: str, params: Dict[str, Any], action_id: str, source: str, rationale: str = "") -> None:
        param_str = f"({_fmt_params(params)})" if params else ""
        rat = f'  rationale="{rationale[:100]}"' if rationale else ""
        self._write(f"t+{self._elapsed():05.2f}  → {action}{param_str}   id={action_id}  source={source}{rat}")
        if self._jsonl_fh is not None:
            self._jsonl_fh.write(json.dumps({
                "t": round(self._elapsed(), 3),
                "kind": "action_request",
                "action": action,
                "parameters": params,
                "id": action_id,
                "source": source,
                "rationale": rationale,
            }) + "\n")

    def action_event(self, action_id: str, status: str, message: str) -> None:
        marker = {
            "accepted":  "← accepted ",
            "running":   "← running  ",
            "completed": "← completed",
            "failed":    "← failed   ",
            "cancelled": "← cancelled",
            "rejected":  "← rejected ",
        }.get(status, f"← {status:<9}")
        msg = f'  "{message}"' if message else ""
        self._write(f"t+{self._elapsed():05.2f}  {marker}   id={action_id}{msg}")
        if self._jsonl_fh is not None:
            self._jsonl_fh.write(json.dumps({
                "t": round(self._elapsed(), 3),
                "kind": "action_event",
                "id": action_id,
                "status": status,
                "message": message,
            }) + "\n")

    def note(self, text: str) -> None:
        self._write(f"t+{self._elapsed():05.2f}  # {text}")

    def target_found(self, name: str, distance: Optional[float]) -> None:
        dist = f"{distance:.2f} m" if distance is not None else "unknown distance"
        self._write(f"t+{self._elapsed():05.2f}  ★ TARGET FOUND: {name!r} at {dist}")

    def result(self, metrics: Dict[str, Any], verdict: str, verdict_reason: str) -> None:
        self._write("")
        self._write("== result ==")
        for key, value in metrics.items():
            self._write(f"    {key:<25}: {value}")
        self._write(f"    verdict                  : {verdict}   {verdict_reason}")
        # Persist metrics + verdict as a machine-readable sidecar.
        self.metrics_path.write_text(json.dumps({
            "verdict": verdict,
            "verdict_reason": verdict_reason,
            **metrics,
        }, indent=2))


def _fmt_vec(vec: Any) -> str:
    if not isinstance(vec, (list, tuple)) or len(vec) < 3:
        return str(vec)
    return f"[{vec[0]:.2f}, {vec[1]:.2f}, {vec[2]:.2f}]"


def _fmt_params(params: Dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in params.items())


@contextmanager
def open_run(run_dir: Path) -> Iterator[PrettyRunWriter]:
    silence_noise()
    with PrettyRunWriter(run_dir) as w:
        yield w
