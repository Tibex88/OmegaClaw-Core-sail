"""Demo runner: exercises S01 against a fake Unity so you can inspect the pretty log.

Not part of the pytest suite. Run manually:
    .venv-bridge/bin/python -m experiments.tests.demo_log_format
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import threading
from pathlib import Path

from bridge.tests.fake_unity import FakeUnityServer, sample_snapshot
from experiments.scenarios import s01_deterministic_smoke
from experiments.scenarios.base import Scenario, run_scenario


class _AsyncFakeUnity:
    def __init__(self, **server_kwargs):
        self.server = FakeUnityServer(**server_kwargs)
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


async def _amain(runs_root: Path) -> int:
    harness = _AsyncFakeUnity(running_updates=1, running_delay=0.05, terminal_delay=0.05)
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
            for _ in range(8):
                harness.broadcast(sample_snapshot())
                await asyncio.sleep(0.2)

        run_task = asyncio.create_task(run_scenario(scenario, runs_root))
        drip_task = asyncio.create_task(_drip())
        run_dir = await run_task
        await drip_task

        print(f"\n=== log at {run_dir}/run.log ===\n")
        print((run_dir / "run.log").read_text())
        print("=== metrics.json ===")
        print((run_dir / "metrics.json").read_text())
        return 0
    finally:
        harness.close()


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1] / "runs"
    root.mkdir(parents=True, exist_ok=True)
    sys.exit(asyncio.run(_amain(root)))
