"""Demo runner: exercises the harness against a fake Unity with a stubbed LLM
so you can inspect the pretty log format without hitting MiniMax.

Not part of the pytest suite. Run manually:
    .venv-bridge/bin/python -m experiments.tests.demo_log_format
"""
from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

from bridge.policy import MiniMaxPolicy
from bridge.tests.fake_unity import FakeUnityServer, sample_snapshot
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


class _StubChat:
    _REPLIES = [
        '{"Action": "RotateRight", "Parameters": {}, "Rationale": "look right first"}',
        '{"Action": "RotateLeft",  "Parameters": {}, "Rationale": "then back left"}',
        '{"Action": "MoveAhead",   "Parameters": {"Distance": 0.3}, "Rationale": "step forward"}',
    ]

    def __init__(self) -> None:
        self._i = 0

    def __call__(self, prompt: str) -> str:
        if self._i < len(self._REPLIES):
            r = self._REPLIES[self._i]
            self._i += 1
            return r
        return "{}"


async def _amain(runs_root: Path) -> int:
    harness = _AsyncFakeUnity(running_updates=1, running_delay=0.05, terminal_delay=0.05)
    try:
        stub = _StubChat()
        scenario = Scenario(
            id="DEMO",
            name="stubbed_llm_smoke",
            description="Stubbed LLM issues RotateRight → RotateLeft → MoveAhead(0.3) "
                        "against the in-process fake Unity so the pretty log format can "
                        "be inspected without hitting a real LLM.",
            policy_factory=lambda: MiniMaxPolicy(chat_fn=stub),
            duration_seconds=6.0,
            gap_seconds=0.1,
            endpoint=harness.url,
            verdict=lambda metrics: (
                "PASS" if metrics.get("actions_completed", 0) >= 1 else "FAIL",
                f"{metrics.get('actions_completed', 0)} action(s) completed",
            ),
        )

        async def _drip():
            for _ in range(15):
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
