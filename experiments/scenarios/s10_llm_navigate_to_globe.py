"""S10 — Free-form goal: 'Reach the Globe and Interact with it'."""
from __future__ import annotations

from experiments.scenarios._llm_common import minimax_policy_factory
from experiments.scenarios.base import Scenario


_GOAL = (
    "Your objective is to reach the destination named 'Globe' and Interact with it. "
    "Prefer MoveTo Globe when Globe is present in AvailableActions.Player.MoveTo. "
    "If Globe is not currently advertised (out of range), explore by rotating or "
    "moving until it becomes advertised. Once close, use Interact. Do not do "
    "anything else until Globe is reached and interacted with."
)


def _verdict(metrics: dict) -> tuple[str, str]:
    completed = metrics.get("actions_completed", 0)
    rejected_bridge = metrics.get("actions_rejected_by_bridge", 0)
    if completed >= 1 and rejected_bridge == 0:
        return "PASS", (f"OmegaSen followed the goal — {completed} valid actions completed. "
                       f"Inspect the run.log to see whether it chose MoveTo Globe and Interacted.")
    if rejected_bridge >= 1:
        return "PARTIAL", (f"{rejected_bridge} LLM choices rejected by the bridge; "
                          f"{completed} completed")
    return "PARTIAL", f"requested={metrics.get('actions_requested', 0)} completed={completed}"


SCENARIO = Scenario(
    id="S10",
    name="llm_navigate_to_globe",
    description="Directed MiniMax play toward a concrete destination: reach and Interact "
                "with the Globe. Documents whether the LLM chooses MoveTo (vs. primitives) "
                "when a goal names a known destination.",
    policy_factory=minimax_policy_factory(goal_text=_GOAL),
    duration_seconds=120.0,
    gap_seconds=1.5,
    verdict=_verdict,
    extra_config={"goal": "reach Globe and Interact"},
)
