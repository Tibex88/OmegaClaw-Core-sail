"""Smoke test: run S01 against the in-process fake Unity to prove the harness end-to-end."""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any, Dict

import pytest

from bridge.tests.fake_unity import FakeUnityServer
from experiments.scenarios import s01_deterministic_smoke
from experiments.scenarios.base import Scenario, run_scenario


class _AsyncFakeUnity:
    def __init__(self, **server_kwargs: Any) -> None:
        self.server = FakeUnityServer(**server_kwargs)
        self.loop = asyncio.new_event_loop()
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


@pytest.mark.asyncio
async def test_s01_end_to_end_against_fake_unity(tmp_path: Path) -> None:
    harness = _AsyncFakeUnity(running_updates=1, running_delay=0.02, terminal_delay=0.02)
    try:
        original = s01_deterministic_smoke.SCENARIO
        scenario = Scenario(
            id=original.id,
            name=original.name,
            description=original.description,
            policy_factory=original.policy_factory,
            duration_seconds=6.0,
            gap_seconds=0.05,
            endpoint=harness.url,
            verdict=original.verdict,
        )

        async def _drip():
            from bridge.tests.fake_unity import sample_snapshot
            for _ in range(6):
                harness.broadcast(sample_snapshot())
                await asyncio.sleep(0.15)

        run_task = asyncio.create_task(run_scenario(scenario, tmp_path))
        drip_task = asyncio.create_task(_drip())
        run_dir = await run_task
        await drip_task

        # log file exists, has beautified content
        log_text = (run_dir / "run.log").read_text()
        assert "== S01  " in log_text
        assert "connect" in log_text
        assert "→ RotateRight" in log_text
        assert "→ RotateLeft" in log_text
        assert "→ MoveAhead" in log_text
        assert "← completed" in log_text
        assert "== result ==" in log_text

        # metrics.json parses and verdict is PASS or PARTIAL (fake unity always completes)
        metrics = json.loads((run_dir / "metrics.json").read_text())
        assert metrics["verdict"] in {"PASS", "PARTIAL"}
        assert metrics["actions_completed"] >= 1

        # snapshots.jsonl has structured entries
        jsonl = (run_dir / "snapshots.jsonl").read_text().strip().splitlines()
        assert any("snapshot" in line for line in jsonl)
        assert any("action_request" in line for line in jsonl)
        assert any("action_event" in line for line in jsonl)
    finally:
        harness.close()
