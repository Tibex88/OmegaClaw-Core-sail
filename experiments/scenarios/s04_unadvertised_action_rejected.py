"""S04 — Attempt an action that is not in AvailableActions.Player and verify the bridge blocks it."""
from __future__ import annotations

from bridge.policy import Choice, ScriptedPolicy
from experiments.scenarios.base import Scenario


def _policy():
    # `Fly` is deliberately not part of any Unity actor's action set.
    return ScriptedPolicy([
        Choice(action="Fly", parameters={"Altitude": 5.0}, source="scenario",
               rationale="attempt an unadvertised action to test the guardrail"),
    ])


def _verdict(metrics: dict) -> tuple[str, str]:
    rejected_bridge = metrics.get("actions_rejected_by_bridge", 0)
    requested = metrics.get("actions_requested", 0)
    if rejected_bridge >= 1 and requested == 0:
        return "PASS", "bridge rejected 'Fly' locally; nothing sent to Unity"
    if requested >= 1:
        return "FAIL", "bridge forwarded an unadvertised action to Unity"
    return "PARTIAL", f"rejected={rejected_bridge} requested={requested}"


SCENARIO = Scenario(
    id="S04",
    name="unadvertised_action_rejected",
    description="Tries to invoke 'Fly', which never appears in AvailableActions.Player. "
                "Verifies bridge-side validation prevents the request from reaching Unity.",
    policy_factory=_policy,
    duration_seconds=6.0,
    gap_seconds=0.1,
    verdict=_verdict,
)
