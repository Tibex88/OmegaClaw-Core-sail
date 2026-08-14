"""S05 — LLM asked to run five rotations quickly; bridge serialises them."""
from __future__ import annotations

from experiments.scenarios._llm_common import minimax_policy_factory
from experiments.scenarios.base import Scenario


_GOAL = (
    "Perform five rotations in quick succession, alternating: (1) RotateLeft "
    "(2) RotateRight (3) RotateLeft (4) RotateRight (5) RotateLeft. Each on its "
    "own turn. The bridge enforces one-action-at-a-time, so wait for each "
    "rotation to reach a terminal status before choosing the next. After all "
    "five have completed, return an empty JSON object {} on every subsequent turn."
)


def _verdict(metrics: dict) -> tuple[str, str]:
    completed = metrics.get("actions_completed", 0)
    rejected_bridge = metrics.get("actions_rejected_by_bridge", 0)
    if completed >= 5 and rejected_bridge == 0:
        return "PASS", f"LLM issued {completed} rotations; all serialized cleanly"
    if completed >= 3:
        return "PARTIAL", f"only {completed}/5 completed within the time budget"
    return "FAIL", f"only {completed} rotations completed"


SCENARIO = Scenario(
    id="S05",
    name="llm_one_in_flight",
    description="LLM is asked to perform five rotations back-to-back. Documents "
                "OmegaSen's ability to sequence multiple actions and shows the "
                "one-in-flight lock in operation.",
    policy_factory=minimax_policy_factory(goal_text=_GOAL),
    duration_seconds=90.0,
    gap_seconds=1.0,
    verdict=_verdict,
)
