"""S09 — LLM-driven search for 'Crixi' with the 3-minute ceiling."""
from __future__ import annotations

from experiments.scenarios._llm_common import minimax_policy_factory
from experiments.scenarios.base import Scenario
from bridge.__main__ import _goal_for_find  # noqa: WPS433


_TARGET = "Crixi"


def _verdict(metrics: dict) -> tuple[str, str]:
    found = metrics.get("target_found")
    completed = metrics.get("actions_completed", 0)
    rejected_bridge = metrics.get("actions_rejected_by_bridge", 0)
    if found:
        distance = metrics.get("target_found_distance")
        dist = f"{distance:.2f} m" if distance is not None else "unknown distance"
        return "SURPRISE", f"LLM located {found!r} at {dist} — Crixi is apparently in the scene"
    if completed >= 3:
        return "PASS", (f"3-min ceiling reached without finding Crixi (expected); "
                       f"LLM chose {completed} valid actions, {rejected_bridge} rejected")
    return "PARTIAL", f"only {completed} actions completed; LLM may be stuck or latency-bound"


SCENARIO = Scenario(
    id="S09",
    name="llm_search_crixi_180s",
    description=f"OmegaSen (MiniMax) actively searches the scene for {_TARGET!r}. The "
                f"bridge scans perception in parallel and exits on match. Documents "
                f"how the LLM explores when it has a target it cannot find.",
    policy_factory=minimax_policy_factory(goal_text=_goal_for_find(_TARGET)),
    duration_seconds=180.0,
    gap_seconds=1.5,
    find_target=_TARGET,
    verdict=_verdict,
    extra_config={"target": _TARGET, "expected_outcome": "timeout (target absent)"},
)
