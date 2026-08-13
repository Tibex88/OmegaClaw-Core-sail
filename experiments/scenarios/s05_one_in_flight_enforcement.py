"""S05 — Fire five actions with GAP=0 and confirm they serialize, one at a time."""
from __future__ import annotations

from bridge.policy import Choice, ScriptedPolicy
from experiments.scenarios.base import Scenario


def _policy():
    return ScriptedPolicy([
        Choice(action="RotateRight", parameters={}, source="scenario"),
        Choice(action="RotateLeft",  parameters={}, source="scenario"),
        Choice(action="RotateRight", parameters={}, source="scenario"),
        Choice(action="RotateLeft",  parameters={}, source="scenario"),
        Choice(action="RotateRight", parameters={}, source="scenario"),
    ])


def _verdict(metrics: dict) -> tuple[str, str]:
    completed = metrics.get("actions_completed", 0)
    requested = metrics.get("actions_requested", 0)
    rejected_bridge = metrics.get("actions_rejected_by_bridge", 0)
    if completed >= 5 and rejected_bridge == 0:
        return "PASS", f"all 5 actions serialized cleanly ({completed}/{requested} completed)"
    if completed >= 1:
        return "PARTIAL", f"only {completed}/5 completed within the time budget"
    return "FAIL", f"no actions completed (requested={requested})"


SCENARIO = Scenario(
    id="S05",
    name="one_in_flight_enforcement",
    description="Submits five back-to-back rotations with GAP=0. Since ScriptedPolicy only "
                "emits when idle and the tracker enforces one-in-flight, all five must "
                "serialize with no overlap.",
    policy_factory=_policy,
    duration_seconds=30.0,
    gap_seconds=0.0,
    verdict=_verdict,
)
