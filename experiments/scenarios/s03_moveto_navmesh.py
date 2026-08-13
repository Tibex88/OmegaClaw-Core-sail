"""S03 — MoveTo the first advertised destination via NavMesh."""
from __future__ import annotations

from typing import Optional

from bridge.policy import Choice, Policy
from bridge.snapshot import Snapshot
from experiments.scenarios.base import Scenario


class _FirstMoveToPolicy(Policy):
    """Picks the first advertised MoveTo target on the first snapshot, then stops."""

    name = "first_move_to"

    def __init__(self) -> None:
        self._fired = False

    async def choose(self, snapshot: Snapshot, *, active: bool = False) -> Optional[Choice]:
        if active or self._fired:
            return None
        targets = snapshot.player_actions.move_to_targets
        if not targets:
            return None
        target = targets[0]
        self._fired = True
        return Choice(
            action="MoveTo",
            parameters={"Target": target},
            source=self.name,
            rationale=f"navigate to first advertised destination: {target}",
        )


def _policy() -> Policy:
    return _FirstMoveToPolicy()


def _verdict(metrics: dict) -> tuple[str, str]:
    completed = metrics.get("actions_completed", 0)
    failed = metrics.get("actions_failed", 0)
    rejected_bridge = metrics.get("actions_rejected_by_bridge", 0)
    rejected_unity = metrics.get("actions_rejected_by_unity", 0)
    requested = metrics.get("actions_requested", 0)
    if requested == 0 and rejected_bridge == 0:
        return "FAIL", "no snapshot ever advertised a MoveTo target"
    if completed >= 1:
        return "PASS", "reached the destination via NavMesh"
    if failed >= 1:
        return "PARTIAL", "MoveTo failed (stall or NavMesh path incomplete)"
    if rejected_unity >= 1:
        return "PARTIAL", "Unity rejected the MoveTo target"
    return "PARTIAL", f"submitted={requested} but no terminal completion observed"


SCENARIO = Scenario(
    id="S03",
    name="moveto_navmesh",
    description="Uses AvailableActions.Player.MoveTo to send the Player to the first "
                "advertised destination via Unity's NavMesh. Documents completion time.",
    policy_factory=_policy,
    duration_seconds=45.0,
    gap_seconds=0.5,
    verdict=_verdict,
)
