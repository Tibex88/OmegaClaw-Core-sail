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
        return (
            "You are OmegaClaw controlling the Player in SophiaVerse. "
            "Choose ONE action for the Player. Only pick from AvailableActions.Player. "
            "Return strict JSON with keys Action, Parameters (object), Rationale (<=140 chars). "
            "For MoveTo, Parameters must be {\"Target\": <target-name-from-MoveTo-list>}. "
            "For primitives (RotateLeft, RotateRight, MoveAhead), Parameters may be an empty object. "
            "No preamble, no code fence, JSON only.\n"
            f"STATE:\n{json.dumps(state, ensure_ascii=False)}"
        )


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
