from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest

from bridge.policy import Choice, ScriptedPolicy
from bridge.sophiaverse_bridge import BridgeConfig, UnityBridge
from bridge.tests.fake_unity import FakeUnityServer, sample_snapshot


def _ids():
    counter = [0]

    def factory() -> str:
        counter[0] += 1
        return f"omega-live-{counter[0]:03d}"

    return factory


@pytest.mark.asyncio
async def test_live_sequence_rotate_rotate_move_cancel():
    """Same protocol as Unity; exercises the four demo steps end-to-end."""
    in_flight: Dict[str, Dict[str, Any]] = {}

    async def _handler(server: FakeUnityServer, request: Dict[str, Any], connection) -> None:
        action = request.get("Action")
        if action == "Cancel":
            for other in list(in_flight.values()):
                await server._emit_result(  # noqa: SLF001
                    connection, other, "cancelled", "interrupted by Cancel",
                )
                in_flight.pop(other["ActionId"], None)
            await server._emit_result(connection, request, "completed", "cancel ack")  # noqa: SLF001
            return

        in_flight[request["ActionId"]] = request
        await server._emit_result(connection, request, "accepted", "fake accepted")  # noqa: SLF001

        if action == "MoveAhead":
            # Emit running updates for long enough that Cancel arrives first.
            for _ in range(20):
                await asyncio.sleep(0.05)
                if request["ActionId"] not in in_flight:
                    return
                await server._emit_result(  # noqa: SLF001
                    connection, request, "running", "fake running",
                )
            if request["ActionId"] in in_flight:
                await server._emit_result(  # noqa: SLF001
                    connection, request, "completed", "fake completed",
                )
                in_flight.pop(request["ActionId"], None)
            return

        await asyncio.sleep(0.05)
        await server._emit_result(connection, request, "completed", "fake completed")  # noqa: SLF001
        in_flight.pop(request["ActionId"], None)

    server = FakeUnityServer(action_handler=_handler)
    await server.start()
    try:
        policy = ScriptedPolicy([
            Choice(action="RotateRight", parameters={}, source="demo"),
            Choice(action="RotateLeft", parameters={}, source="demo"),
            Choice(action="MoveAhead", parameters={"Distance": 0.3}, source="demo"),
            Choice(action="Cancel", parameters={}, source="demo"),
        ])
        events = []
        bridge = UnityBridge(
            policy,
            config=BridgeConfig(
                endpoint=server.url,
                min_seconds_between_actions=0.0,
                action_timeout_seconds=10.0,
            ),
            action_id_factory=_ids(),
            on_action_event=lambda rec: events.append((rec.action, rec.status)),
        )

        async def _drive():
            await asyncio.sleep(0.05)
            # Drip snapshots so each step gets its own decision point.
            for _ in range(6):
                await server.broadcast(sample_snapshot())
                await asyncio.sleep(0.1)
            # Wait for scripted policy to drain.
            while policy.remaining > 0:
                await asyncio.sleep(0.05)
                await server.broadcast(sample_snapshot())
            # Let terminal statuses land.
            await asyncio.sleep(0.6)
            bridge.request_stop()

        await asyncio.gather(bridge.run(), _drive())

        submitted_actions = [
            m["Action"] for m in server.received if m.get("Type") == "game.action.request"
        ]
        assert submitted_actions == ["RotateRight", "RotateLeft", "MoveAhead", "Cancel"]

        # Every submitted action reached a terminal state (completed or cancelled).
        terminal_by_action: Dict[str, str] = {}
        for action, status in events:
            if status in {"completed", "cancelled", "failed", "rejected"}:
                terminal_by_action[action] = status

        assert terminal_by_action.get("RotateRight") == "completed"
        assert terminal_by_action.get("RotateLeft") == "completed"
        assert terminal_by_action.get("MoveAhead") == "cancelled"
        assert terminal_by_action.get("Cancel") == "completed"
    finally:
        await server.stop()
