"""S02 — LLM starts a long MoveAhead, then chooses Cancel to interrupt it."""
from __future__ import annotations

from experiments.scenarios._llm_common import minimax_policy_factory
from experiments.scenarios.base import Scenario


_GOAL = (
    "This turn: emit MoveAhead with Parameters {\"Distance\": 2.0}. On the NEXT turn, "
    "while MoveAhead is still running (you will see it in the active_action field), "
    "emit Cancel with empty Parameters to interrupt it. After Cancel completes, "
    "return an empty JSON object {} on every subsequent turn. Do not do anything "
    "else."
)


def _verdict(metrics: dict) -> tuple[str, str]:
    cancelled = metrics.get("actions_cancelled", 0)
    completed = metrics.get("actions_completed", 0)
    if cancelled >= 1 and completed >= 1:
        return "PASS", f"MoveAhead cancelled by LLM ({cancelled} cancelled, {completed} completed)"
    if completed >= 1 and cancelled == 0:
        return "PARTIAL", "LLM never emitted Cancel; MoveAhead ran to completion"
    return "FAIL", "no valid actions completed"


SCENARIO = Scenario(
    id="S02",
    name="llm_cancel_mid_flight",
    description="LLM is instructed to start a long MoveAhead, then Cancel it on the "
                "next turn while it is still running. Documents whether OmegaSen can "
                "reason about mid-action interruption.",
    policy_factory=minimax_policy_factory(goal_text=_GOAL),
    duration_seconds=60.0,
    gap_seconds=1.0,
    verdict=_verdict,
)
