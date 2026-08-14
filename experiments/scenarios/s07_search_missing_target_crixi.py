"""S07 — Search for 'Crixi' which does not exist in the scene, hit the 3-minute ceiling."""
from __future__ import annotations

from bridge.policy import DeterministicPolicy
from experiments.scenarios.base import Scenario


_TARGET = "Crixi"


def _policy():
    return DeterministicPolicy(["RotateRight", "RotateLeft", "MoveAhead"])


def _verdict(metrics: dict) -> tuple[str, str]:
    if metrics.get("target_found"):
        # Unexpected — flag it as a surprise for follow-up.
        return "SURPRISE", f"Crixi actually appears in the scene as {metrics['target_found']!r}"
    if metrics.get("actions_completed", 0) >= 3:
        return "PASS", "explored for the full duration without finding a non-existent target (expected)"
    return "PARTIAL", "duration elapsed with fewer than 3 completed actions — exploration stalled"


SCENARIO = Scenario(
    id="S07",
    name="search_missing_target_crixi",
    description=f"Hunts for {_TARGET!r} using deterministic exploration for 3 minutes. "
                f"Crixi is not in the scene, so this documents behavior when a search "
                f"target never resolves and the time budget is the terminating condition.",
    policy_factory=_policy,
    duration_seconds=180.0,
    gap_seconds=0.5,
    find_target=_TARGET,
    verdict=_verdict,
    extra_config={"target": _TARGET, "expected_outcome": "timeout (target absent)"},
)
