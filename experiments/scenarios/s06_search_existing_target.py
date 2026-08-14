"""S06 — Deterministic exploration + target detection on an entity that should exist."""
from __future__ import annotations

from bridge.policy import DeterministicPolicy
from experiments.scenarios.base import Scenario


# `Interactable` matches PasswordInteractableCollider, HumanityTestInteractable, etc.
# We used entity Names from earlier live logs, so this should always resolve
# in the loaded scene.
_TARGET = "Interactable"


def _policy():
    return DeterministicPolicy(["RotateRight", "RotateLeft", "MoveAhead"])


def _verdict(metrics: dict) -> tuple[str, str]:
    if metrics.get("target_found"):
        distance = metrics.get("target_found_distance")
        dist = f"{distance:.2f} m" if distance is not None else "unknown distance"
        return "PASS", f"found {metrics['target_found']!r} at {dist}"
    return "PARTIAL", "search completed the time budget without spotting the target"


SCENARIO = Scenario(
    id="S06",
    name="search_existing_target",
    description=f"Uses DeterministicPolicy to rotate/step while the bridge scans "
                f"perception for {_TARGET!r}. Exits early on first match. "
                f"Documents time to discovery.",
    policy_factory=_policy,
    duration_seconds=60.0,
    gap_seconds=0.5,
    find_target=_TARGET,
    verdict=_verdict,
    extra_config={"target": _TARGET},
)
