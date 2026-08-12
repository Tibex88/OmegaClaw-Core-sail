"""End-to-end WebSocket bridge: Unity snapshots → policy → validated action → lifecycle tracking."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

import websockets

from .action_state import ActionAlreadyActive, ActionRecord, ActionTracker
from .policy import Choice, InvalidAction, Policy, validate_choice
from .snapshot import PLAYER_ACTOR, Snapshot, is_action_result, parse_snapshot

log = logging.getLogger(__name__)

DEFAULT_ENDPOINT = os.environ.get("UNITY_GAME_STATE_URL", "ws://127.0.0.1:8765/game/state")


@dataclass
class BridgeConfig:
    endpoint: str = DEFAULT_ENDPOINT
    action_timeout_seconds: float = 30.0
    min_seconds_between_actions: float = 0.5


class BridgeMetrics:
    def __init__(self) -> None:
        self.snapshots_received = 0
        self.snapshots_malformed = 0
        self.actions_requested = 0
        self.actions_rejected_by_bridge = 0
        self.actions_rejected_by_unity = 0
        self.actions_completed = 0
        self.actions_failed = 0
        self.actions_cancelled = 0
        self.actions_timed_out = 0

    def as_dict(self) -> Dict[str, int]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


ActionIdFactory = Callable[[], str]
SendCallable = Callable[[str], Awaitable[None]]


def _default_action_id() -> str:
    return f"omega-{uuid.uuid4().hex[:12]}"


class UnityBridge:
    """Owns the WebSocket connection, dispatches snapshots to a policy, tracks lifecycles."""

    def __init__(
        self,
        policy: Policy,
        config: Optional[BridgeConfig] = None,
        *,
        action_id_factory: ActionIdFactory = _default_action_id,
        on_snapshot: Optional[Callable[[Snapshot], None]] = None,
        on_action_event: Optional[Callable[[ActionRecord], None]] = None,
    ) -> None:
        self.policy = policy
        self.config = config or BridgeConfig()
        self.tracker = ActionTracker()
        self.metrics = BridgeMetrics()
        self._action_id_factory = action_id_factory
        self._on_snapshot = on_snapshot
        self._last_action_time: float = 0.0
        self._connection: Optional[Any] = None
        self._stop = asyncio.Event()
        if on_action_event is not None:
            self.tracker.subscribe(on_action_event)

    async def run(self) -> None:
        log.info("Connecting to Unity at %s", self.config.endpoint)
        async with websockets.connect(self.config.endpoint) as ws:
            self._connection = ws
            try:
                await self._read_loop(ws)
            finally:
                self._connection = None

    def request_stop(self) -> None:
        self._stop.set()

    async def process_message(self, message: str) -> None:
        """Public entry point for tests: consume a single Unity message."""
        await self._handle_raw(message, send=self._send_stub_if_no_conn())

    def _send_stub_if_no_conn(self) -> SendCallable:
        async def _noop(_: str) -> None:
            return None
        return _noop

    async def _read_loop(self, ws: Any) -> None:
        async def _send(payload: str) -> None:
            await ws.send(payload)

        while not self._stop.is_set():
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                await self._check_timeout(_send)
                continue
            except websockets.ConnectionClosed:
                log.info("Unity closed the WebSocket connection")
                return

            await self._handle_raw(message, send=_send)
            await self._check_timeout(_send)

    async def _handle_raw(self, raw: str, send: SendCallable) -> None:
        try:
            payload: Dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.metrics.snapshots_malformed += 1
            log.warning("Ignoring non-JSON message: %s", exc)
            return

        message_type = payload.get("Type")
        if message_type == "game.state.snapshot":
            await self._handle_snapshot(payload, send)
        elif is_action_result(payload):
            self._handle_result(payload)
        else:
            log.debug("Ignoring message of type %s", message_type)

    async def _handle_snapshot(self, payload: Dict[str, Any], send: SendCallable) -> None:
        try:
            snapshot = parse_snapshot(payload)
        except Exception as exc:  # noqa: BLE001
            self.metrics.snapshots_malformed += 1
            log.warning("Malformed snapshot: %s", exc)
            return

        self.metrics.snapshots_received += 1
        if self._on_snapshot is not None:
            try:
                self._on_snapshot(snapshot)
            except Exception:  # noqa: BLE001
                log.exception("on_snapshot listener raised")

        loop_now = asyncio.get_event_loop().time()
        active_record = self.tracker.active
        active = active_record is not None and not active_record.is_terminal
        cooled_down = loop_now - self._last_action_time >= self.config.min_seconds_between_actions

        # Skip policy entirely when nothing can be submitted anyway. This
        # avoids consuming stateful policies (e.g. ScriptedPolicy) that pop a
        # choice we would just discard.
        if not active and not cooled_down:
            return

        try:
            choice = await self.policy.choose(snapshot, active=active)
        except Exception:  # noqa: BLE001
            log.exception("Policy raised while choosing an action")
            return

        if choice is None:
            return

        is_cancel = choice.action == "Cancel"
        if active and not is_cancel:
            log.debug(
                "Dropping non-Cancel choice while %s is in flight",
                active_record.action_id if active_record else None,
            )
            return

        try:
            validate_choice(choice, snapshot.player_actions)
        except InvalidAction as exc:
            self.metrics.actions_rejected_by_bridge += 1
            log.warning("Bridge rejected policy choice: %s", exc)
            return

        await self._submit(choice, send)

    async def _submit(self, choice: Choice, send: SendCallable) -> None:
        action_id = self._action_id_factory()
        record = ActionRecord(
            action_id=action_id,
            actor=PLAYER_ACTOR,
            action=choice.action,
            parameters=dict(choice.parameters),
        )
        try:
            await self.tracker.submit(record)
        except ActionAlreadyActive:
            self.metrics.actions_rejected_by_bridge += 1
            return

        request = choice.to_request(action_id)
        self.metrics.actions_requested += 1
        self._last_action_time = asyncio.get_event_loop().time()
        log.info(
            "→ Unity: action=%s params=%s id=%s source=%s rationale=%s",
            choice.action, choice.parameters, action_id, choice.source, choice.rationale,
        )
        try:
            await send(json.dumps(request))
        except Exception:  # noqa: BLE001
            log.exception("Failed to send action request")
            record.apply("failed", "send failed")

    def _handle_result(self, payload: Dict[str, Any]) -> None:
        record = self.tracker.apply_result(payload)
        if record is None:
            log.debug("Unknown ActionId in result: %s", payload)
            return

        status = record.status
        log.info(
            "← Unity: id=%s status=%s message=%s", record.action_id, status, record.last_message,
        )
        if status == "completed":
            self.metrics.actions_completed += 1
        elif status == "failed":
            self.metrics.actions_failed += 1
        elif status == "cancelled":
            self.metrics.actions_cancelled += 1
        elif status == "rejected":
            self.metrics.actions_rejected_by_unity += 1

    async def _check_timeout(self, send: SendCallable) -> None:
        record = self.tracker.active
        if record is None or record.is_terminal:
            return
        elapsed = asyncio.get_event_loop().time() - self._last_action_time
        if elapsed < self.config.action_timeout_seconds:
            return

        log.warning("Action %s exceeded timeout; requesting Cancel", record.action_id)
        cancel_id = self._action_id_factory()
        cancel_request = {
            "Type": "game.action.request",
            "ActionId": cancel_id,
            "Actor": PLAYER_ACTOR,
            "Action": "Cancel",
            "Parameters": {},
        }
        self.metrics.actions_timed_out += 1
        try:
            await send(json.dumps(cancel_request))
        except Exception:  # noqa: BLE001
            log.exception("Failed to send Cancel request")
        record.apply("cancelled", "bridge timeout → Cancel dispatched")
