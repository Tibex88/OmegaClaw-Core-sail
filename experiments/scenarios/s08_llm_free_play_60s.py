"""S08 — Undirected LLM play for 60 seconds. Baseline for prompt quality."""
from __future__ import annotations

from experiments.scenarios._llm_common import minimax_policy_factory
from experiments.scenarios.base import Scenario


def _verdict(metrics: dict) -> tuple[str, str]:
    requested = metrics.get("actions_requested", 0)
    completed = metrics.get("actions_completed", 0)
    rejected_bridge = metrics.get("actions_rejected_by_bridge", 0)
    if requested >= 1 and completed >= 1 and rejected_bridge == 0:
        return "PASS", f"OmegaSen chose and completed {completed} actions across {requested} attempts"
    if rejected_bridge >= 1:
        return "PARTIAL", f"LLM invented {rejected_bridge} unadvertised actions; {completed} valid completions"
    if requested == 0:
        return "FAIL", "LLM never emitted a valid decision (check response parsing or the empty-content fallback)"
    return "PARTIAL", f"requested={requested} completed={completed}"


SCENARIO = Scenario(
    id="S08",
    name="llm_free_play_60s",
    description="Undirected MiniMax play for 60 seconds. No goal text. Baseline for how "
                "OmegaSen behaves when told only the world model and action catalog.",
    policy_factory=minimax_policy_factory(),
    duration_seconds=60.0,
    gap_seconds=1.5,
    verdict=_verdict,
)
