"""S07 — LLM searches for 'Crixi' (absent). Time budget is the terminator."""
from __future__ import annotations

from bridge.__main__ import _goal_for_find  # noqa: WPS433
from experiments.scenarios._llm_common import minimax_policy_factory
from experiments.scenarios.base import Scenario


_TARGET = "Crixi"


def _verdict(metrics: dict) -> tuple[str, str]:
    if metrics.get("target_found"):
        return "SURPRISE", (f"OmegaSen located {metrics['target_found']!r} — "
                            f"Crixi is apparently in the scene after all")
    completed = metrics.get("actions_completed", 0)
    if completed >= 5:
        return "PASS", (f"3-min ceiling reached without finding Crixi (expected); "
                       f"LLM completed {completed} exploration actions")
    return "PARTIAL", f"only {completed} actions completed — LLM may be stuck or slow"


SCENARIO = Scenario(
    id="S07",
    name="llm_search_missing_target_crixi",
    description=f"OmegaSen (MiniMax) searches for {_TARGET!r} which is not in the "
                f"scene. Documents behavior when a search target never resolves "
                f"and the 3-minute time budget is the terminating condition.",
    policy_factory=minimax_policy_factory(goal_text=_goal_for_find(_TARGET)),
    duration_seconds=180.0,
    gap_seconds=1.0,
    find_target=_TARGET,
    verdict=_verdict,
    extra_config={"target": _TARGET, "expected_outcome": "timeout (target absent)"},
)
