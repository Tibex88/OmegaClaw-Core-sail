"""Action-selection policies. Every choice is validated against advertised actions."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .snapshot import PLAYER_ACTOR, AvailableActions, Snapshot

log = logging.getLogger(__name__)


class InvalidAction(ValueError):
    """Raised when a chosen action is not advertised by Unity for the Player."""


@dataclass(frozen=True)
class Choice:
    action: str
    parameters: Dict[str, Any]
    source: str
    rationale: str = ""

    def to_request(self, action_id: str, actor: str = PLAYER_ACTOR) -> Dict[str, Any]:
        return {
            "Type": "game.action.request",
            "ActionId": action_id,
            "Actor": actor,
            "Action": self.action,
            "Parameters": dict(self.parameters),
        }


def validate_choice(choice: Choice, available: AvailableActions) -> None:
    target = choice.parameters.get("Target") if isinstance(choice.parameters, dict) else None
    if choice.action == "Cancel":
        return
    if not available.has_action(choice.action, target):
        raise InvalidAction(
            f"Action {choice.action!r} target={target!r} is not in the current advertised set: "
            f"{available.flatten()}"
        )


class Policy:
    """Base policy. Subclasses return a Choice or None (skip this snapshot)."""

    name = "base"

    async def choose(self, snapshot: Snapshot, *, active: bool = False) -> Optional[Choice]:
        raise NotImplementedError


class DeterministicPolicy(Policy):
    """Cycle through a small, safe primitive sequence. Skips if nothing safe is advertised."""

    name = "deterministic"

    SAFE_PRIMITIVES = ("RotateRight", "RotateLeft", "MoveAhead")

    def __init__(self, sequence: Optional[List[str]] = None) -> None:
        self._sequence = list(sequence) if sequence else list(self.SAFE_PRIMITIVES)
        self._index = 0

    async def choose(self, snapshot: Snapshot, *, active: bool = False) -> Optional[Choice]:
        if active:
            return None
        available = snapshot.player_actions
        for _ in range(len(self._sequence)):
            candidate = self._sequence[self._index % len(self._sequence)]
            self._index += 1
            if candidate in available.primitives:
                params: Dict[str, Any] = {}
                if candidate == "MoveAhead":
                    params["Distance"] = 0.3
                return Choice(action=candidate, parameters=params, source=self.name,
                              rationale=f"deterministic cycle → {candidate}")
        return None


class ScriptedPolicy(Policy):
    """Emit prescribed Choices in order. Cancel is only emitted while an action is active."""

    name = "scripted"

    def __init__(self, choices: List[Choice]) -> None:
        self._choices = list(choices)

    async def choose(self, snapshot: Snapshot, *, active: bool = False) -> Optional[Choice]:
        if not self._choices:
            return None
        next_choice = self._choices[0]
        is_cancel = next_choice.action == "Cancel"
        if is_cancel and not active:
            return None
        if not is_cancel and active:
            return None
        self._choices.pop(0)
        return next_choice

    @property
    def remaining(self) -> int:
        return len(self._choices)


_JSON_BLOCK = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


class MiniMaxPolicy(Policy):
    """Ask MiniMax to pick a Player action. Requires ASI_API_KEY at import site."""

    name = "minimax"

    def __init__(
        self,
        chat_fn: Callable[[str], str],
        *,
        max_perception_entities: int = 6,
    ) -> None:
        self._chat = chat_fn
        self._max_entities = max_perception_entities

    async def choose(self, snapshot: Snapshot, *, active: bool = False) -> Optional[Choice]:
        if active:
            return None
        prompt = self._build_prompt(snapshot)
        raw = await asyncio.to_thread(self._chat, prompt)
        payload = _extract_json_object(raw)
        if payload is None:
            log.warning("MiniMax response did not contain a JSON object: %s", raw[:200])
            return None

        action = str(payload.get("Action") or "").strip()
        parameters = payload.get("Parameters") or {}
        if not action or not isinstance(parameters, dict):
            log.warning("MiniMax response missing Action/Parameters: %s", payload)
            return None

        rationale = str(payload.get("Rationale") or "")[:200]
        return Choice(
            action=action,
            parameters={str(k): v for k, v in parameters.items()},
            source=self.name,
            rationale=rationale,
        )

    SYSTEM = (
        "You are OmegaSen, an AI agent controlling the Player avatar in SAIL, "
        "a 3D SophiaVerse environment. You are distinct from Sen, a separate "
        "on-screen actor; you never issue Sen actions.\n"
        "\n"
        "WORLD:\n"
        "- The scene contains destinations (registered points of interest), "
        "interactables (objects with an Interact action), and scene objects "
        "(walls, decor). Kinds are reported in each visible entity.\n"
        "- The Player has a raycast_metadata sensor: a grid of first-hit rays "
        "from the camera, each reporting Name, Kinds, Position, Distance (m), "
        "AngleDegrees (from view center), SurfaceNormal, and AvailableActions "
        "for that entity.\n"
        "\n"
        "ACTIONS (only pick from AvailableActions.Player, never invent):\n"
        "- MoveAhead / MoveBack / MoveLeft / MoveRight — optional "
        "Parameters: {\"Distance\": 0.1..2.0}, default 0.5 m.\n"
        "- RotateLeft / RotateRight — optional Parameters: "
        "{\"Degrees\": 1..90}, default 15°.\n"
        "- MoveTo — required Parameters: {\"Target\": <name>}, "
        "where <name> is from AvailableActions.Player.MoveTo. NavMesh path.\n"
        "- Interact — Parameters may specify a target from a visible entity "
        "whose AvailableActions include \"Interact\".\n"
        "- Cancel — no parameters. Interrupts the in-flight action.\n"
        "\n"
        "RULES:\n"
        "- Only one Player action at a time; do not issue a new action while one "
        "is running (the bridge enforces this).\n"
        "- Only choose actions currently in AvailableActions.Player. MoveTo "
        "targets change as the Player moves.\n"
        "- Prefer small primitives when uncertain. Use MoveTo when a valid "
        "destination is advertised. Use Interact for interactables.\n"
        "- If nothing safe is possible, return an empty JSON object {}.\n"
        "\n"
        "OUTPUT (strict JSON, no code fence, no prose):\n"
        "{\"Action\": <string>, \"Parameters\": <object>, "
        "\"Rationale\": <string, <=140 chars>}\n"
    )

    def _build_prompt(self, snapshot: Snapshot) -> str:
        visible = list((snapshot.player_perception.get("VisibleEntities") or [])[: self._max_entities])
        compact_visible = [
            {
                "Name": entity.get("Name"),
                "Kinds": entity.get("Kinds", []),
                "Distance": entity.get("Distance"),
                "AngleDegrees": entity.get("AngleDegrees"),
                "AvailableActions": entity.get("AvailableActions", []),
            }
            for entity in visible
        ]
        advertised = {
            "Primitive": snapshot.player_actions.primitives,
            "MoveTo": snapshot.player_actions.move_to_targets,
            "Other": snapshot.player_actions.other,
        }
        state = {
            "PlayerStatus": snapshot.player_status,
            "PlayerPerception": {
                "ObservationMode": snapshot.player_perception.get("ObservationMode"),
                "VisibleEntities": compact_visible,
            },
            "SenState": snapshot.sen_perception,
            "AvailableActions.Player": advertised,
        }
        return f"{self.SYSTEM}\nSTATE:\n{json.dumps(state, ensure_ascii=False)}"


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    stripped = text.strip()
    for candidate in (stripped, _strip_code_fence(stripped)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    match = _JSON_BLOCK.search(stripped)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _strip_code_fence(text: str) -> str:
    if text.startswith("```"):
        without = text.split("```", 2)
        if len(without) >= 3:
            return without[1].lstrip("json").strip()
    return text
