"""S03 — LLM picks a destination and issues MoveTo."""
from __future__ import annotations

from experiments.scenarios._llm_common import minimax_policy_factory
from experiments.scenarios.base import Scenario


_GOAL = (
    "Look at AvailableActions.Player.MoveTo. Pick the FIRST destination name from "
    "that list. Emit a MoveTo action with Parameters {\"Target\": <that name>}. "
    "After MoveTo reaches a terminal status, return an empty JSON object {} on "
    "every subsequent turn. Do not choose a different destination."
)


def _verdict(metrics: dict) -> tuple[str, str]:
    completed = metrics.get("actions_completed", 0)
    failed = metrics.get("actions_failed", 0)
    rejected_bridge = metrics.get("actions_rejected_by_bridge", 0)
    rejected_unity = metrics.get("actions_rejected_by_unity", 0)
    requested = metrics.get("actions_requested", 0)
    if completed >= 1:
        return "PASS", "OmegaSen chose a destination and MoveTo reached completion"
    if failed >= 1:
        return "PARTIAL", "MoveTo failed (stall or NavMesh path incomplete)"
    if rejected_unity >= 1:
        return "PARTIAL", "Unity rejected the MoveTo target"
    if rejected_bridge >= 1:
        return "PARTIAL", "LLM proposed an invalid MoveTo target; bridge rejected"
    if requested == 0:
        return "FAIL", "LLM never emitted a MoveTo request"
    return "PARTIAL", f"requested={requested} but no terminal completion observed"


SCENARIO = Scenario(
    id="S03",
    name="llm_moveto_navmesh",
    description="LLM is asked to pick the first advertised MoveTo destination and "
                "navigate to it via NavMesh. Documents whether OmegaSen chooses "
                "MoveTo (over primitives) when a destination is available.",
    policy_factory=minimax_policy_factory(goal_text=_GOAL),
    duration_seconds=60.0,
    gap_seconds=1.0,
    verdict=_verdict,
)
