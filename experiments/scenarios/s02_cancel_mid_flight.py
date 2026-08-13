"""S02 — Cancel a MoveAhead mid-flight and verify lifecycle."""
from __future__ import annotations

from bridge.policy import Choice, ScriptedPolicy
from experiments.scenarios.base import Scenario


def _policy():
    return ScriptedPolicy([
        Choice(action="MoveAhead", parameters={"Distance": 1.5}, source="scenario"),
        # Cancel only emits when an action is active, so this fires on the
        # next snapshot after MoveAhead is submitted.
        Choice(action="Cancel", parameters={}, source="scenario",
               rationale="interrupt the long MoveAhead"),
    ])


def _verdict(metrics: dict) -> tuple[str, str]:
    cancelled = metrics.get("actions_cancelled", 0)
    completed = metrics.get("actions_completed", 0)
    requested = metrics.get("actions_requested", 0)
    if requested < 2:
        return "FAIL", f"expected 2 requests (MoveAhead + Cancel), got {requested}"
    if cancelled >= 1 and completed >= 1:
        return "PASS", f"MoveAhead cancelled, Cancel completed ({cancelled} cancelled / {completed} completed)"
    return "PARTIAL", f"cancelled={cancelled} completed={completed}"


SCENARIO = Scenario(
    id="S02",
    name="cancel_mid_flight",
    description="Submits a long MoveAhead, then Cancel while it is still running. "
                "Verifies Cancel bypasses the one-in-flight lock and terminates the active action.",
    policy_factory=_policy,
    duration_seconds=15.0,
    gap_seconds=0.5,
    verdict=_verdict,
)
