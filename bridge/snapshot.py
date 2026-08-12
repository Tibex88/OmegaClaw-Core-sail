"""Parse and validate Unity game.state.snapshot messages (schema 2.2)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SUPPORTED_SCHEMA = "2.2"
SNAPSHOT_TYPE = "game.state.snapshot"
RESULT_TYPE = "game.action.result"
PLAYER_ACTOR = "Player"


class SnapshotError(ValueError):
    """Raised when a snapshot payload is malformed or unsupported."""


@dataclass(frozen=True)
class AvailableActions:
    primitives: List[str] = field(default_factory=list)
    move_to_targets: List[str] = field(default_factory=list)
    other: Dict[str, List[Any]] = field(default_factory=dict)

    def has_action(self, name: str, target: Optional[str] = None) -> bool:
        if name in self.primitives and target is None:
            return True
        if name == "MoveTo":
            return target is not None and target in self.move_to_targets
        candidates = self.other.get(name)
        return candidates is not None and (target is None or target in candidates)

    def flatten(self) -> List[str]:
        rows = list(self.primitives)
        rows.extend(f"MoveTo({t})" for t in self.move_to_targets)
        for name, params in self.other.items():
            if params:
                rows.extend(f"{name}({p})" for p in params)
            else:
                rows.append(name)
        return rows


@dataclass(frozen=True)
class Snapshot:
    schema_version: str
    timestamp_utc: str
    controlled_entity: str
    controller: str
    player_status: Dict[str, Any]
    player_perception: Dict[str, Any]
    sen_perception: Dict[str, Any]
    player_actions: AvailableActions
    sen_actions: Dict[str, List[Any]]
    raw: Dict[str, Any]


def parse_actions(actions_by_name: Dict[str, Any]) -> AvailableActions:
    if not isinstance(actions_by_name, dict):
        raise SnapshotError("AvailableActions per-actor block must be an object")

    primitives = list(actions_by_name.get("Primitive", []) or [])
    move_to = list(actions_by_name.get("MoveTo", []) or [])
    other = {
        k: list(v or [])
        for k, v in actions_by_name.items()
        if k not in {"Primitive", "MoveTo"}
    }
    return AvailableActions(primitives=primitives, move_to_targets=move_to, other=other)


def parse_snapshot(message: Dict[str, Any]) -> Snapshot:
    if not isinstance(message, dict):
        raise SnapshotError("Snapshot must be a JSON object")

    if message.get("Type") != SNAPSHOT_TYPE:
        raise SnapshotError(f"Expected Type={SNAPSHOT_TYPE!r}, got {message.get('Type')!r}")

    schema = message.get("SchemaVersion")
    if schema != SUPPORTED_SCHEMA:
        raise SnapshotError(f"Unsupported schema version {schema!r}; expected {SUPPORTED_SCHEMA!r}")

    payload = message.get("Payload")
    if not isinstance(payload, dict):
        raise SnapshotError("Snapshot Payload is missing or not an object")

    u_input = payload.get("UInput")
    if not isinstance(u_input, dict):
        raise SnapshotError("Payload.UInput is missing or not an object")

    perceptions = u_input.get("Perceptions")
    if not isinstance(perceptions, dict):
        raise SnapshotError("Payload.UInput.Perceptions is missing or not an object")

    available_actions = payload.get("AvailableActions")
    if not isinstance(available_actions, dict):
        raise SnapshotError("Payload.AvailableActions is missing or not an object")

    player_actions_raw = available_actions.get(PLAYER_ACTOR)
    if not isinstance(player_actions_raw, dict):
        raise SnapshotError("Payload.AvailableActions.Player must be an object")

    return Snapshot(
        schema_version=schema,
        timestamp_utc=str(message.get("TimestampUtc", "")),
        controlled_entity=str(payload.get("ControlledEntity", "")),
        controller=str(payload.get("Controller", "")),
        player_status=dict(u_input.get("PlayerStatus") or {}),
        player_perception=dict(perceptions.get(PLAYER_ACTOR) or {}),
        sen_perception=dict(perceptions.get("Sen") or {}),
        player_actions=parse_actions(player_actions_raw),
        sen_actions={k: list(v or []) for k, v in (available_actions.get("Sen") or {}).items()},
        raw=message,
    )


def is_action_result(message: Dict[str, Any]) -> bool:
    return isinstance(message, dict) and message.get("Status") is not None and "ActionId" in message
