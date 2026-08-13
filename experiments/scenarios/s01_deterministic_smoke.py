"""S01 — Deterministic smoke: RotateRight, RotateLeft, MoveAhead(0.3)."""
from __future__ import annotations

from bridge.policy import Choice, ScriptedPolicy
from experiments.scenarios.base import Scenario


def _policy():
    return ScriptedPolicy([
        Choice(action="RotateRight", parameters={}, source="scenario"),
        Choice(action="RotateLeft",  parameters={}, source="scenario"),
        Choice(action="MoveAhead",   parameters={"Distance": 0.3}, source="scenario"),
    ])


def _verdict(metrics: dict) -> tuple[str, str]:
    if metrics["actions_completed"] >= 3 and metrics["actions_rejected_by_bridge"] == 0:
        return "PASS", "all three scripted actions completed"
    if metrics["actions_completed"] == 0:
        return "FAIL", "no actions completed — check Unity/scene wiring"
    return "PARTIAL", f"only {metrics['actions_completed']}/3 actions completed"


SCENARIO = Scenario(
    id="S01",
    name="deterministic_smoke",
    description="Sends RotateRight, RotateLeft, MoveAhead(0.3) via ScriptedPolicy. "
                "Verifies the wire loop is healthy end-to-end.",
    policy_factory=_policy,
    duration_seconds=15.0,
    gap_seconds=0.5,
    verdict=_verdict,
)
