"""Verify channels/game_ws.py against the same fake Unity used by the bridge."""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "channels") not in sys.path:
    sys.path.insert(0, str(_REPO / "channels"))

import game_ws  # noqa: E402
from bridge.tests.fake_unity import FakeUnityServer, sample_snapshot  # noqa: E402


class _AsyncServerHarness:
    """Runs a FakeUnityServer inside a dedicated background asyncio loop so
    the synchronous game_ws client can connect over real TCP.
    """

    def __init__(self, **server_kwargs: Any) -> None:
        self.server = FakeUnityServer(**server_kwargs)
        self.loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self._thread.start()
        self.url = self._run(self.server.start())

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()

    def broadcast(self, payload: Dict[str, Any]) -> None:
        self._run(self.server.broadcast(payload))

    def close(self) -> None:
        try:
            self._run(self.server.stop())
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self._thread.join(timeout=2.0)
            self.loop.close()


def _reset_channel_state() -> None:
    with game_ws._state_lock:  # noqa: SLF001
        game_ws._last_snapshot = None  # noqa: SLF001
        game_ws._last_snapshot_epoch = 0  # noqa: SLF001
        game_ws._last_snapshot_delivered = 0  # noqa: SLF001
        game_ws._action_records.clear()  # noqa: SLF001
        game_ws._action_events.clear()  # noqa: SLF001
        game_ws._active_action_id = None  # noqa: SLF001
        game_ws._last_submitted_action_id = None  # noqa: SLF001


def _wait_until(predicate, timeout: float = 3.0, tick: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(tick)
    return False


def _start_channel(harness: _AsyncServerHarness) -> None:
    game_ws.start_game_ws(harness.url)
    assert _wait_until(lambda: game_ws._connected), "channel never connected"  # noqa: SLF001


def _teardown(harness: _AsyncServerHarness) -> None:
    game_ws.stop_game_ws()
    harness.close()
    _reset_channel_state()


def test_receive_returns_snapshot_summary_once_per_epoch():
    _reset_channel_state()
    harness = _AsyncServerHarness()
    _start_channel(harness)
    try:
        harness.broadcast(sample_snapshot())
        assert _wait_until(lambda: game_ws._last_snapshot is not None)  # noqa: SLF001

        first = game_ws.getLastMessage()
        assert first.startswith("SNAPSHOT ")
        parsed = json.loads(first.removeprefix("SNAPSHOT "))
        assert parsed["schema"] == "2.2"
        assert parsed["controlled"] == "Player"
        assert "MoveAhead" in parsed["actions"]["Primitive"]

        # Second call without a new snapshot returns empty (so MeTTa loop doesn't
        # re-trigger on the same input).
        assert game_ws.getLastMessage() == ""

        # A new snapshot lifts the epoch and delivers a fresh summary.
        harness.broadcast(sample_snapshot(position=[1.0, 2.0, 3.0]))
        assert _wait_until(lambda: game_ws.getLastMessage() != "")
    finally:
        _teardown(harness)


def test_send_action_rejects_unadvertised_locally():
    _reset_channel_state()
    harness = _AsyncServerHarness()
    _start_channel(harness)
    try:
        harness.broadcast(sample_snapshot(primitives=["RotateLeft"]))
        assert _wait_until(lambda: game_ws._last_snapshot is not None)  # noqa: SLF001

        result = game_ws.send_action("MoveAhead", {})
        assert result.startswith("REJECTED_LOCALLY")
        # Server must not have received the bogus request.
        assert not any(msg.get("Type") == "game.action.request" for msg in harness.server.received)
    finally:
        _teardown(harness)


def test_send_action_lifecycle_tracked_and_slot_frees_on_terminal():
    _reset_channel_state()
    harness = _AsyncServerHarness(running_updates=1, running_delay=0.02, terminal_delay=0.02)
    _start_channel(harness)
    try:
        harness.broadcast(sample_snapshot())
        assert _wait_until(lambda: game_ws._last_snapshot is not None)  # noqa: SLF001

        result = game_ws.send_action("RotateRight", {})
        assert result.startswith("SENT: id=")

        # Concurrent request while first is in flight must be refused as BUSY.
        second = game_ws.send_action("RotateLeft", {})
        assert second.startswith("BUSY")

        # Wait for terminal; slot frees, next request goes through.
        status = game_ws.wait_for_terminal(2.0)
        assert status == "completed"
        third = game_ws.send_action("RotateLeft", {})
        assert third.startswith("SENT: id=")

        assert _wait_until(lambda: game_ws.wait_for_terminal(2.0) in {"completed", "idle"})
    finally:
        _teardown(harness)


def test_cancel_bypasses_busy_check():
    _reset_channel_state()
    harness = _AsyncServerHarness(running_updates=5, running_delay=0.2, terminal_delay=0.2)
    _start_channel(harness)
    try:
        harness.broadcast(sample_snapshot())
        assert _wait_until(lambda: game_ws._last_snapshot is not None)  # noqa: SLF001

        first = game_ws.send_action("MoveAhead", {"Distance": 0.3})
        assert first.startswith("SENT: id=")
        # Cancel goes through even while MoveAhead is running.
        cancel_result = game_ws.send_action("Cancel", {})
        assert cancel_result.startswith("SENT: id=")

        assert _wait_until(
            lambda: any(m.get("Action") == "Cancel" for m in harness.server.received)
        ), "Cancel never observed on the server"
        cancel_requests = [m for m in harness.server.received if m.get("Action") == "Cancel"]
        assert len(cancel_requests) == 1
    finally:
        _teardown(harness)


def test_perceive_returns_summary_without_advancing_delivery():
    _reset_channel_state()
    harness = _AsyncServerHarness()
    _start_channel(harness)
    try:
        harness.broadcast(sample_snapshot())
        assert _wait_until(lambda: game_ws._last_snapshot is not None)  # noqa: SLF001

        # perceive() must not consume the "new snapshot" flag getLastMessage cares about.
        summary = game_ws.perceive()
        assert summary.startswith("SNAPSHOT ")
        summary_again = game_ws.getLastMessage()
        assert summary_again.startswith("SNAPSHOT ")
    finally:
        _teardown(harness)
