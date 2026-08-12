"""Run a fake Unity in-process and drive the real bridge CLI against it.

Prints the message transcript. Not part of the automated test suite; invoke via:
    .venv-bridge/bin/python -m bridge.tests.manual_live_run
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, List

from bridge.policy import Choice, ScriptedPolicy
from bridge.sophiaverse_bridge import BridgeConfig, UnityBridge
from bridge.tests.fake_unity import FakeUnityServer, sample_snapshot


async def _run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("manual-live")

    in_flight: Dict[str, Dict[str, Any]] = {}

    async def handler(server: FakeUnityServer, request: Dict[str, Any], connection) -> None:
        action = request.get("Action")
        if action == "Cancel":
            for other in list(in_flight.values()):
                await server._emit_result(connection, other, "cancelled", "interrupted by Cancel")  # noqa: SLF001
                in_flight.pop(other["ActionId"], None)
            await server._emit_result(connection, request, "completed", "cancel ack")  # noqa: SLF001
            return

        in_flight[request["ActionId"]] = request
        await server._emit_result(connection, request, "accepted", "unity accepted")  # noqa: SLF001

        if action == "MoveAhead":
            for _ in range(30):
                await asyncio.sleep(0.05)
                if request["ActionId"] not in in_flight:
                    return
                await server._emit_result(connection, request, "running", "moving forward")  # noqa: SLF001
            if request["ActionId"] in in_flight:
                await server._emit_result(connection, request, "completed", "moved 0.3m")  # noqa: SLF001
                in_flight.pop(request["ActionId"], None)
            return

        await asyncio.sleep(0.08)
        await server._emit_result(connection, request, "completed", "rotation done")  # noqa: SLF001
        in_flight.pop(request["ActionId"], None)

    server = FakeUnityServer(action_handler=handler)
    endpoint = await server.start()
    log.info("Fake Unity listening at %s", endpoint)

    transcript: List[Dict[str, Any]] = []
    policy = ScriptedPolicy([
        Choice(action="RotateRight", parameters={}, source="live", rationale="step 1"),
        Choice(action="RotateLeft", parameters={}, source="live", rationale="step 2"),
        Choice(action="MoveAhead", parameters={"Distance": 0.3}, source="live", rationale="step 3"),
        Choice(action="Cancel", parameters={}, source="live", rationale="step 4"),
    ])
    bridge = UnityBridge(
        policy,
        config=BridgeConfig(
            endpoint=endpoint,
            min_seconds_between_actions=0.0,
            action_timeout_seconds=10.0,
        ),
        on_snapshot=lambda snap: transcript.append({
            "kind": "snapshot",
            "advertised": snap.player_actions.flatten(),
            "position": snap.player_status.get("Position"),
        }),
        on_action_event=lambda rec: transcript.append({
            "kind": "action_event",
            "id": rec.action_id,
            "action": rec.action,
            "status": rec.status,
            "message": rec.last_message,
        }),
    )

    async def _drive() -> None:
        await asyncio.sleep(0.1)
        for _ in range(20):
            await server.broadcast(sample_snapshot())
            await asyncio.sleep(0.15)
            if policy.remaining == 0 and (bridge.tracker.active is None or bridge.tracker.active.is_terminal):
                break
        await asyncio.sleep(0.4)
        bridge.request_stop()

    try:
        await asyncio.gather(bridge.run(), _drive())
    finally:
        await server.stop()

    print("\n=== transcript ===")
    for entry in transcript:
        print(json.dumps(entry))
    print("\n=== metrics ===")
    print(json.dumps(bridge.metrics.as_dict(), indent=2))
    print("\n=== unity received ===")
    for entry in server.received:
        print(json.dumps(entry))

    ok = (
        bridge.metrics.actions_requested == 4
        and bridge.metrics.actions_completed >= 2
        and bridge.metrics.actions_cancelled >= 1
    )
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
