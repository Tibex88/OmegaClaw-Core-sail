from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

import pytest

from bridge.action_state import ActionRecord
from bridge.policy import Choice, DeterministicPolicy, InvalidAction, Policy, validate_choice
from bridge.snapshot import parse_snapshot
from bridge.sophiaverse_bridge import BridgeConfig, UnityBridge
from bridge.tests.fake_unity import FakeUnityServer, sample_snapshot


class _ScriptedPolicy(Policy):
    name = "scripted"

    def __init__(self, choices: List[Optional[Choice]]) -> None:
        self._choices = list(choices)
        self.calls = 0

    async def choose(self, snapshot, *, active: bool = False):
        self.calls += 1
        if active:
            return None
        return self._choices.pop(0) if self._choices else None


def _mkchoice(action: str, **params: Any) -> Choice:
    return Choice(action=action, parameters=params, source="test")


def _monotonic_ids():
    counter = [0]

    def factory() -> str:
        counter[0] += 1
        return f"aid-{counter[0]}"

    return factory


def test_validate_rejects_unadvertised():
    snap = parse_snapshot(sample_snapshot(primitives=["RotateLeft"]))
    with pytest.raises(InvalidAction):
        validate_choice(_mkchoice("MoveAhead"), snap.player_actions)
    with pytest.raises(InvalidAction):
        validate_choice(_mkchoice("MoveTo", Target="Mars"), snap.player_actions)


def test_validate_accepts_advertised_and_cancel():
    snap = parse_snapshot(sample_snapshot())
    validate_choice(_mkchoice("RotateLeft"), snap.player_actions)
    validate_choice(_mkchoice("MoveTo", Target="Globe"), snap.player_actions)
    validate_choice(_mkchoice("Cancel"), snap.player_actions)


@pytest.mark.asyncio
async def test_deterministic_policy_cycles_only_over_available():
    policy = DeterministicPolicy(["MoveAhead", "RotateLeft"])
    snap = parse_snapshot(sample_snapshot(primitives=["RotateLeft"]))
    choice = await policy.choose(snap)
    assert choice is not None and choice.action == "RotateLeft"


@pytest.mark.asyncio
async def test_end_to_end_deterministic_lifecycle():
    server = FakeUnityServer(running_updates=1, running_delay=0.01, terminal_delay=0.01)
    await server.start()
    try:
        policy = DeterministicPolicy(["RotateRight"])
        bridge = UnityBridge(
            policy,
            config=BridgeConfig(endpoint=server.url, min_seconds_between_actions=0.0,
                                action_timeout_seconds=10.0),
            action_id_factory=_monotonic_ids(),
        )

        async def _drive():
            await asyncio.sleep(0.05)
            await server.broadcast(sample_snapshot(primitives=["RotateRight"]))
            await asyncio.wait_for(_wait_actions_completed(bridge, 1), timeout=3.0)
            bridge.request_stop()

        await asyncio.gather(bridge.run(), _drive())

        assert bridge.metrics.actions_requested == 1
        assert bridge.metrics.actions_completed == 1
        assert bridge.metrics.actions_rejected_by_bridge == 0
        assert bridge.metrics.actions_rejected_by_unity == 0
        submitted = [msg for msg in server.received if msg.get("Type") == "game.action.request"]
        assert len(submitted) == 1
        assert submitted[0]["Action"] == "RotateRight"
        assert submitted[0]["Actor"] == "Player"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_bridge_rejects_unavailable_choice_locally():
    snap_payload = sample_snapshot(primitives=["RotateLeft"])  # no MoveAhead advertised
    policy = _ScriptedPolicy([_mkchoice("MoveAhead")])
    bridge = UnityBridge(
        policy,
        config=BridgeConfig(endpoint="ws://unused", min_seconds_between_actions=0.0),
        action_id_factory=_monotonic_ids(),
    )
    await bridge.process_message(json.dumps(snap_payload))
    assert bridge.metrics.actions_rejected_by_bridge == 1
    assert bridge.metrics.actions_requested == 0


@pytest.mark.asyncio
async def test_bridge_ignores_malformed_json_and_bad_snapshots():
    bridge = UnityBridge(
        _ScriptedPolicy([]),
        config=BridgeConfig(endpoint="ws://unused"),
        action_id_factory=_monotonic_ids(),
    )
    await bridge.process_message("{not-json")
    bad = sample_snapshot()
    del bad["Payload"]["AvailableActions"]
    await bridge.process_message(json.dumps(bad))
    assert bridge.metrics.snapshots_malformed == 2
    assert bridge.metrics.snapshots_received == 0


@pytest.mark.asyncio
async def test_bridge_serializes_actions_one_at_a_time():
    server = FakeUnityServer(running_updates=2, running_delay=0.05, terminal_delay=0.05)
    await server.start()
    try:
        policy = _ScriptedPolicy([_mkchoice("RotateRight"), _mkchoice("RotateLeft")])
        bridge = UnityBridge(
            policy,
            config=BridgeConfig(endpoint=server.url, min_seconds_between_actions=0.0,
                                action_timeout_seconds=10.0),
            action_id_factory=_monotonic_ids(),
        )

        async def _drive():
            await asyncio.sleep(0.05)
            # Blast three snapshots quickly; only one action must be in flight.
            for _ in range(3):
                await server.broadcast(sample_snapshot())
                await asyncio.sleep(0.02)
            await asyncio.wait_for(_wait_actions_completed(bridge, 1), timeout=3.0)
            # Now the first is done, so the next snapshot may spawn the second action.
            await server.broadcast(sample_snapshot())
            await asyncio.wait_for(_wait_actions_completed(bridge, 2), timeout=3.0)
            bridge.request_stop()

        await asyncio.gather(bridge.run(), _drive())

        assert bridge.metrics.actions_requested == 2
        assert bridge.metrics.actions_completed == 2
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_bridge_records_rejection_from_unity():
    server = FakeUnityServer(reject_actions=True)
    await server.start()
    try:
        policy = DeterministicPolicy(["RotateRight"])
        bridge = UnityBridge(
            policy,
            config=BridgeConfig(endpoint=server.url, min_seconds_between_actions=0.0,
                                action_timeout_seconds=10.0),
            action_id_factory=_monotonic_ids(),
        )

        async def _drive():
            await asyncio.sleep(0.05)
            await server.broadcast(sample_snapshot())
            await asyncio.wait_for(_wait_metric(bridge, "actions_rejected_by_unity", 1), timeout=3.0)
            bridge.request_stop()

        await asyncio.gather(bridge.run(), _drive())
        assert bridge.metrics.actions_rejected_by_unity == 1
        assert bridge.metrics.actions_completed == 0
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_bridge_sends_cancel_on_timeout():
    async def _hang(server: FakeUnityServer, request: Dict[str, Any], connection) -> None:
        if request.get("Action") == "Cancel":
            await server._emit_result(connection, request, "completed", "cancel ack")  # noqa: SLF001
            return
        await server._emit_result(connection, request, "accepted", "hang")  # noqa: SLF001

    server = FakeUnityServer(action_handler=_hang)
    await server.start()
    try:
        policy = DeterministicPolicy(["RotateRight"])
        bridge = UnityBridge(
            policy,
            config=BridgeConfig(
                endpoint=server.url,
                min_seconds_between_actions=0.0,
                action_timeout_seconds=0.3,
            ),
            action_id_factory=_monotonic_ids(),
        )

        async def _drive():
            await asyncio.sleep(0.05)
            await server.broadcast(sample_snapshot())
            await asyncio.wait_for(_wait_metric(bridge, "actions_timed_out", 1), timeout=5.0)
            bridge.request_stop()

        await asyncio.gather(bridge.run(), _drive())
        assert bridge.metrics.actions_timed_out == 1
        cancels = [msg for msg in server.received if msg.get("Action") == "Cancel"]
        assert len(cancels) == 1
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_bridge_detects_find_target_in_perception():
    bridge = UnityBridge(
        _ScriptedPolicy([]),
        config=BridgeConfig(endpoint="ws://unused", find_target="Crixi"),
        action_id_factory=_monotonic_ids(),
    )
    visible = [
        {"Name": "Wall_1", "Kinds": ["scene_object"], "Distance": 2.0, "AngleDegrees": 5.0, "AvailableActions": []},
        {"Name": "CrixiStatue", "Kinds": ["interactable", "scene_object"], "Distance": 3.4, "AngleDegrees": -2.1, "AvailableActions": ["Interact"]},
    ]
    await bridge.process_message(json.dumps(sample_snapshot(visible=visible)))
    assert bridge.metrics.target_found == "CrixiStatue"
    assert bridge.metrics.target_found_distance == pytest.approx(3.4)


@pytest.mark.asyncio
async def test_bridge_target_only_flagged_when_visible():
    bridge = UnityBridge(
        _ScriptedPolicy([]),
        config=BridgeConfig(endpoint="ws://unused", find_target="Crixi"),
        action_id_factory=_monotonic_ids(),
    )
    await bridge.process_message(json.dumps(sample_snapshot()))
    assert bridge.metrics.target_found is None


async def _wait_actions_completed(bridge: UnityBridge, count: int) -> None:
    while bridge.metrics.actions_completed < count:
        await asyncio.sleep(0.02)


async def _wait_metric(bridge: UnityBridge, name: str, value: int) -> None:
    while getattr(bridge.metrics, name) < value:
        await asyncio.sleep(0.02)
