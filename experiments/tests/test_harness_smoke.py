"""Smoke test the scenario harness end-to-end using a stubbed LLM.

Every scenario now uses MiniMax, so we can't hit the real API from pytest.
This test wraps a MiniMaxPolicy around a fake chat_fn that returns a valid
JSON action, then runs one scenario through the full harness and inspects
the produced artifacts (run.log, metrics.json, snapshots.jsonl).
"""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from bridge.policy import MiniMaxPolicy
from bridge.tests.fake_unity import FakeUnityServer, sample_snapshot
from experiments.scenarios.base import Scenario, run_scenario


class _AsyncFakeUnity:
    def __init__(self, **kwargs: Any) -> None:
        self.server = FakeUnityServer(**kwargs)
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self._thread.start()
        self.url = asyncio.run_coroutine_threadsafe(self.server.start(), self.loop).result()

    def broadcast(self, payload):
        return asyncio.run_coroutine_threadsafe(self.server.broadcast(payload), self.loop).result()

    def close(self):
        try:
            asyncio.run_coroutine_threadsafe(self.server.stop(), self.loop).result()
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self._thread.join(timeout=2.0)


class _StubChat:
    """Deterministic replacement for MiniMax during pytest."""

    _RESPONSES = [
        '{"Action": "RotateRight", "Parameters": {}, "Rationale": "stub 1"}',
        '{"Action": "RotateLeft",  "Parameters": {}, "Rationale": "stub 2"}',
        '{"Action": "MoveAhead",   "Parameters": {"Distance": 0.3}, "Rationale": "stub 3"}',
    ]

    def __init__(self) -> None:
        self._i = 0

    def __call__(self, prompt: str) -> str:
        if self._i < len(self._RESPONSES):
            reply = self._RESPONSES[self._i]
            self._i += 1
            return reply
        return "{}"


@pytest.mark.asyncio
async def test_scenario_harness_produces_expected_artifacts(tmp_path: Path) -> None:
    harness = _AsyncFakeUnity(running_updates=1, running_delay=0.02, terminal_delay=0.02)
    try:
        stub = _StubChat()
        scenario = Scenario(
            id="STUB",
            name="stubbed_llm_smoke",
            description="Harness smoke: stubbed chat_fn drives MiniMaxPolicy to run "
                        "three actions against the fake Unity.",
            policy_factory=lambda: MiniMaxPolicy(chat_fn=stub),
            duration_seconds=6.0,
            gap_seconds=0.1,
            endpoint=harness.url,
            verdict=lambda metrics: ("PASS", "harness executed"),
        )

        async def _drip():
            for _ in range(30):
                harness.broadcast(sample_snapshot())
                await asyncio.sleep(0.1)

        run_task = asyncio.create_task(run_scenario(scenario, tmp_path))
        drip_task = asyncio.create_task(_drip())
        run_dir = await run_task
        await drip_task

        log_text = (run_dir / "run.log").read_text()
        assert "== STUB" in log_text
        assert "connect" in log_text
        assert "→ RotateRight" in log_text
        assert "← completed" in log_text
        assert "== result ==" in log_text

        metrics = json.loads((run_dir / "metrics.json").read_text())
        assert metrics["verdict"] == "PASS"
        assert metrics["actions_completed"] >= 1

        jsonl_lines = (run_dir / "snapshots.jsonl").read_text().strip().splitlines()
        assert any("action_request" in line for line in jsonl_lines)
        assert any("action_event" in line for line in jsonl_lines)
    finally:
        harness.close()
