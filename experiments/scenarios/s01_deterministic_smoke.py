"""S01 — LLM does a short warm-up sequence.

Goal: OmegaSen performs three primitive actions in order to prove the loop
works end-to-end when driven by MiniMax.
"""
from __future__ import annotations

from experiments.scenarios._llm_common import minimax_policy_factory
from experiments.scenarios.base import Scenario


_GOAL = (
    "This is a warm-up sequence to verify the loop works. Perform exactly three "
    "primitive actions in this order: (1) RotateRight (2) RotateLeft (3) MoveAhead "
    "with Parameters {\"Distance\": 0.3}. After the third action reaches a terminal "
    "status, return an empty JSON object {} on every subsequent turn."
)


def _verdict(metrics: dict) -> tuple[str, str]:
    completed = metrics.get("actions_completed", 0)
    rejected = metrics.get("actions_rejected_by_bridge", 0)
    if completed >= 3 and rejected == 0:
        return "PASS", f"OmegaSen completed {completed} valid actions"
    if completed >= 1:
        return "PARTIAL", f"only {completed}/3 completed; check run.log for the LLM's choices"
    return "FAIL", "no actions completed — LLM never emitted a valid decision"


SCENARIO = Scenario(
    id="S01",
    name="llm_smoke",
    description="LLM warm-up: MiniMax is asked to perform RotateRight, RotateLeft, "
                "MoveAhead(0.3) as a three-action smoke sequence.",
    policy_factory=minimax_policy_factory(goal_text=_GOAL),
    duration_seconds=45.0,
    gap_seconds=1.0,
    verdict=_verdict,
)
