"""S06 — LLM actively searches for an interactable and stops when spotted."""
from __future__ import annotations

from bridge.__main__ import _goal_for_find  # noqa: WPS433
from experiments.scenarios._llm_common import minimax_policy_factory
from experiments.scenarios.base import Scenario


_TARGET = "Interactable"


def _verdict(metrics: dict) -> tuple[str, str]:
    if metrics.get("target_found"):
        distance = metrics.get("target_found_distance")
        dist = f"{distance:.2f} m" if distance is not None else "unknown distance"
        return "PASS", f"OmegaSen located {metrics['target_found']!r} at {dist}"
    completed = metrics.get("actions_completed", 0)
    if completed >= 3:
        return "PARTIAL", "explored for the full duration without spotting the target"
    return "FAIL", f"only {completed} actions completed — LLM barely explored"


SCENARIO = Scenario(
    id="S06",
    name="llm_search_existing_target",
    description=f"OmegaSen (MiniMax) actively searches for an entity whose Name "
                f"contains {_TARGET!r}. The bridge scans perception in parallel "
                f"and exits early on match. Documents LLM-driven exploration.",
    policy_factory=minimax_policy_factory(goal_text=_goal_for_find(_TARGET)),
    duration_seconds=90.0,
    gap_seconds=1.0,
    find_target=_TARGET,
    verdict=_verdict,
    extra_config={"target": _TARGET},
)
