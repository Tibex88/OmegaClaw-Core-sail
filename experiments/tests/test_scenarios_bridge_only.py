"""Verify S01–S05 produce the expected verdict shape against the fake Unity server."""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any, Dict, Set

import pytest

from bridge.tests.fake_unity import FakeUnityServer, sample_snapshot
from experiments.scenarios import (
    s01_deterministic_smoke,
    s02_cancel_mid_flight,
    s03_moveto_navmesh,
    s04_unadvertised_action_rejected,
    s05_one_in_flight_enforcement,
    s06_search_existing_target,
    s07_search_missing_target_crixi,
    s08_llm_free_play_60s,
    s09_llm_search_crixi_180s,
    s10_llm_navigate_to_globe,
)
from experiments.scenarios.base import Scenario, run_scenario


class _AsyncFakeUnity:
    def __init__(self, **kwargs):
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


def _clone(original: Scenario, **overrides) -> Scenario:
    return Scenario(
        id=original.id,
        name=original.name,
        description=original.description,
        policy_factory=original.policy_factory,
        duration_seconds=overrides.get("duration_seconds", original.duration_seconds),
        gap_seconds=overrides.get("gap_seconds", original.gap_seconds),
        find_target=overrides.get("find_target", original.find_target),
        endpoint=overrides["endpoint"],
        verdict=original.verdict,
    )


async def _drip(harness: _AsyncFakeUnity, ticks: int = 40, interval: float = 0.15, **snap_kwargs) -> None:
    for _ in range(ticks):
        harness.broadcast(sample_snapshot(**snap_kwargs))
        await asyncio.sleep(interval)


async def _run(scenario: Scenario, tmp_path: Path, harness: _AsyncFakeUnity, **snap_kwargs) -> Dict[str, Any]:
    run_task = asyncio.create_task(run_scenario(scenario, tmp_path))
    drip_task = asyncio.create_task(_drip(harness, **snap_kwargs))
    run_dir = await run_task
    await drip_task
    return json.loads((run_dir / "metrics.json").read_text())


@pytest.mark.asyncio
async def test_s01_deterministic_smoke_passes(tmp_path: Path) -> None:
    harness = _AsyncFakeUnity(running_updates=1, running_delay=0.02, terminal_delay=0.02)
    try:
        scenario = _clone(s01_deterministic_smoke.SCENARIO,
                          endpoint=harness.url, duration_seconds=5.0, gap_seconds=0.05)
        metrics = await _run(scenario, tmp_path, harness)
        assert metrics["verdict"] == "PASS"
        assert metrics["actions_completed"] >= 3
    finally:
        harness.close()


@pytest.mark.asyncio
async def test_s02_cancel_mid_flight_passes(tmp_path: Path) -> None:
    async def _handler(server, request, connection):
        action = request.get("Action")
        if action == "Cancel":
            # Emit a cancelled result for the previous MoveAhead (id in _pending)
            for other_id in list(_pending):
                await server._emit_result(  # noqa: SLF001
                    connection, _pending[other_id], "cancelled", "interrupted",
                )
                _pending.pop(other_id, None)
            await server._emit_result(connection, request, "completed", "cancel ack")  # noqa: SLF001
            return
        _pending[request["ActionId"]] = request
        await server._emit_result(connection, request, "accepted", "fake")  # noqa: SLF001
        # keep the action "running" long enough for Cancel to arrive
        for _ in range(30):
            await asyncio.sleep(0.05)
            if request["ActionId"] not in _pending:
                return
            await server._emit_result(connection, request, "running", "fake running")  # noqa: SLF001
        if request["ActionId"] in _pending:
            await server._emit_result(connection, request, "completed", "fake completed")  # noqa: SLF001
            _pending.pop(request["ActionId"], None)

    _pending: Dict[str, Dict[str, Any]] = {}
    harness = _AsyncFakeUnity(action_handler=_handler)
    try:
        scenario = _clone(s02_cancel_mid_flight.SCENARIO,
                          endpoint=harness.url, duration_seconds=8.0, gap_seconds=0.1)
        metrics = await _run(scenario, tmp_path, harness)
        assert metrics["verdict"] == "PASS"
        assert metrics["actions_cancelled"] >= 1
        assert metrics["actions_completed"] >= 1
    finally:
        harness.close()


@pytest.mark.asyncio
async def test_s03_moveto_navmesh_passes(tmp_path: Path) -> None:
    harness = _AsyncFakeUnity(running_updates=1, running_delay=0.05, terminal_delay=0.05)
    try:
        scenario = _clone(s03_moveto_navmesh.SCENARIO,
                          endpoint=harness.url, duration_seconds=6.0, gap_seconds=0.05)
        metrics = await _run(scenario, tmp_path, harness)
        assert metrics["verdict"] == "PASS"
        assert metrics["actions_completed"] >= 1
    finally:
        harness.close()


@pytest.mark.asyncio
async def test_s04_unadvertised_action_rejected_passes(tmp_path: Path) -> None:
    harness = _AsyncFakeUnity()
    try:
        scenario = _clone(s04_unadvertised_action_rejected.SCENARIO,
                          endpoint=harness.url, duration_seconds=3.0, gap_seconds=0.05)
        metrics = await _run(scenario, tmp_path, harness)
        assert metrics["verdict"] == "PASS"
        assert metrics["actions_rejected_by_bridge"] >= 1
        assert metrics["actions_requested"] == 0
    finally:
        harness.close()


@pytest.mark.asyncio
async def test_s06_search_finds_target_when_present(tmp_path: Path) -> None:
    harness = _AsyncFakeUnity(running_updates=1, running_delay=0.02, terminal_delay=0.02)
    try:
        # Inject a visible entity whose name contains "Interactable" so S06 finds it.
        visible = [
            {"Name": "PasswordInteractableCollider", "Kinds": ["interactable"],
             "Distance": 3.1, "AngleDegrees": 10.0, "AvailableActions": ["Interact"]},
        ]
        scenario = _clone(s06_search_existing_target.SCENARIO,
                          endpoint=harness.url, duration_seconds=5.0, gap_seconds=0.05)
        metrics = await _run(scenario, tmp_path, harness, ticks=20, interval=0.1, visible=visible)
        assert metrics["verdict"] == "PASS"
        assert metrics["target_found"] == "PasswordInteractableCollider"
    finally:
        harness.close()


@pytest.mark.asyncio
async def test_s07_search_missing_target_hits_ceiling(tmp_path: Path) -> None:
    harness = _AsyncFakeUnity(running_updates=1, running_delay=0.02, terminal_delay=0.02)
    try:
        # Fake Unity broadcasts only walls; Crixi is never visible.
        visible = [
            {"Name": "BigWall1", "Kinds": ["scene_object"],
             "Distance": 2.5, "AngleDegrees": 5.0, "AvailableActions": []},
        ]
        scenario = _clone(s07_search_missing_target_crixi.SCENARIO,
                          endpoint=harness.url, duration_seconds=3.0, gap_seconds=0.05)
        metrics = await _run(scenario, tmp_path, harness, ticks=25, interval=0.1, visible=visible)
        assert metrics["target_found"] is None
        assert metrics["verdict"] in {"PASS", "PARTIAL"}
    finally:
        harness.close()


def test_llm_scenarios_import_and_expose_scenario_objects() -> None:
    for module in (s08_llm_free_play_60s, s09_llm_search_crixi_180s, s10_llm_navigate_to_globe):
        scenario = module.SCENARIO
        assert scenario.id.startswith("S")
        assert callable(scenario.policy_factory)
        assert scenario.duration_seconds > 0
        assert callable(scenario.verdict)


@pytest.mark.asyncio
async def test_s05_one_in_flight_enforcement_passes(tmp_path: Path) -> None:
    async def _handler(server, request, connection):
        active_at_time.add(request["ActionId"])
        overlap_seen[0] = overlap_seen[0] or (len(active_at_time) > 1)
        await server._emit_result(connection, request, "accepted", "fake")  # noqa: SLF001
        await asyncio.sleep(0.02)
        await server._emit_result(connection, request, "completed", "fake completed")  # noqa: SLF001
        active_at_time.discard(request["ActionId"])

    active_at_time: Set[str] = set()
    overlap_seen = [False]
    harness = _AsyncFakeUnity(action_handler=_handler)
    try:
        scenario = _clone(s05_one_in_flight_enforcement.SCENARIO,
                          endpoint=harness.url, duration_seconds=8.0, gap_seconds=0.0)
        metrics = await _run(scenario, tmp_path, harness)
        assert metrics["verdict"] == "PASS"
        assert metrics["actions_completed"] >= 5
        assert overlap_seen[0] is False
    finally:
        harness.close()
