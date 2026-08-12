"""Minimal fake of Unity's /game/state WebSocket server for bridge tests."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import websockets


def sample_snapshot(
    *,
    primitives: Optional[List[str]] = None,
    move_to: Optional[List[str]] = None,
    position: Optional[List[float]] = None,
    visible: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    primitives = primitives if primitives is not None else ["MoveAhead", "RotateLeft", "RotateRight"]
    move_to = move_to if move_to is not None else ["Globe"]
    position = position if position is not None else [14.22, 2.90, 1.24]
    visible = visible if visible is not None else [
        {
            "EntityId": "Game/Environment/Globe",
            "Name": "Globe",
            "IsRegistered": True,
            "Kinds": ["destination", "interactable", "scene_object"],
            "Position": [13.10, 2.90, 6.30],
            "Distance": 5.42,
            "AngleDegrees": 21.5,
            "AvailableActions": ["MoveTo", "Interact"],
        }
    ]
    return {
        "Type": "game.state.snapshot",
        "SchemaVersion": "2.2",
        "TimestampUtc": datetime.now(timezone.utc).isoformat(),
        "Payload": {
            "ControlledEntity": "Player",
            "Controller": "Human",
            "UInput": {
                "PlayerStatus": {"Position": position, "Forward": [0.0, 0.0, 1.0], "IsMoving": False},
                "Perceptions": {
                    "Player": {
                        "ObservationMode": "raycast_metadata",
                        "Observer": "Player",
                        "ViewOrigin": [position[0], position[1] + 1.6, position[2]],
                        "ViewDirection": [0.0, 0.0, 1.0],
                        "FieldOfViewDegrees": 100.0,
                        "MaxDistance": 1500.0,
                        "VisibleEntities": visible,
                    },
                    "Sen": {"Observer": "Sophia", "VisibleEntities": []},
                },
            },
            "AvailableActions": {
                "Player": {"MoveTo": move_to, "Primitive": primitives},
                "Sen": {"WaitForSeconds": [3]},
            },
        },
    }


@dataclass
class FakeUnityServer:
    """In-process WebSocket server that scripts snapshots and reacts to requests."""

    host: str = "127.0.0.1"
    port: int = 0
    reject_actions: bool = False
    silent: bool = False
    accept_delay: float = 0.0
    running_updates: int = 1
    running_delay: float = 0.05
    terminal_delay: float = 0.05
    action_handler: Optional[Callable[["FakeUnityServer", Dict[str, Any], Any], asyncio.Task]] = None
    received: List[Dict[str, Any]] = field(default_factory=list)
    _server: Optional[Any] = None
    _clients: List[Any] = field(default_factory=list)
    _tasks: List[asyncio.Task] = field(default_factory=list)

    async def start(self) -> str:
        self._server = await websockets.serve(self._on_client, self.host, self.port)
        for sock in self._server.sockets or []:
            self.host, self.port = sock.getsockname()[:2]
        return self.url

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for client in list(self._clients):
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}/game/state"

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        message = json.dumps(payload)
        for client in list(self._clients):
            try:
                await client.send(message)
            except Exception:  # noqa: BLE001
                pass

    async def _on_client(self, connection: Any) -> None:
        self._clients.append(connection)
        try:
            async for raw in connection:
                await self._handle_client_message(connection, raw)
        finally:
            if connection in self._clients:
                self._clients.remove(connection)

    async def _handle_client_message(self, connection: Any, raw: str) -> None:
        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            return
        self.received.append(request)
        if self.silent:
            return
        if self.action_handler is not None:
            task = asyncio.create_task(self.action_handler(self, request, connection))
            self._tasks.append(task)
            return

        if self.reject_actions:
            await self._emit_result(connection, request, "rejected", "fake unity rejects everything")
            return

        task = asyncio.create_task(self._default_lifecycle(connection, request))
        self._tasks.append(task)

    async def _default_lifecycle(self, connection: Any, request: Dict[str, Any]) -> None:
        if self.accept_delay:
            await asyncio.sleep(self.accept_delay)
        await self._emit_result(connection, request, "accepted", "fake accepted")
        for _ in range(self.running_updates):
            await asyncio.sleep(self.running_delay)
            await self._emit_result(connection, request, "running", "fake running")
        await asyncio.sleep(self.terminal_delay)
        await self._emit_result(connection, request, "completed", "fake completed")

    async def _emit_result(self, connection: Any, request: Dict[str, Any], status: str, message: str) -> None:
        result = {
            "Type": "game.action.result",
            "ActionId": request.get("ActionId"),
            "Actor": request.get("Actor"),
            "Action": request.get("Action"),
            "Status": status,
            "TimestampUtc": datetime.now(timezone.utc).isoformat(),
            "Message": message,
            "Details": {},
        }
        try:
            await connection.send(json.dumps(result))
        except Exception:  # noqa: BLE001
            pass
