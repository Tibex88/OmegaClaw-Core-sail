"""Scenario base class + async runner.

Each scenario declares a name, description, bridge policy, config knobs, and a
verdict function that inspects the final metrics. The runner wires everything
into a PrettyRunWriter.
"""
from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bridge.policy import Policy  # noqa: E402
from bridge.sophiaverse_bridge import BridgeConfig, UnityBridge  # noqa: E402
from experiments.formatter import PrettyRunWriter, open_run  # noqa: E402


VerdictFn = Callable[[Dict[str, Any]], Tuple[str, str]]


@dataclass
class Scenario:
    """Everything the runner needs to execute one experiment."""

    id: str
    name: str
    description: str
    policy_factory: Callable[[], Policy]
    duration_seconds: float
    gap_seconds: float = 1.0
    find_target: Optional[str] = None
    endpoint: str = "ws://127.0.0.1:8765/game/state"
    verdict: VerdictFn = lambda metrics: ("UNKNOWN", "no verdict function")
    extra_config: Dict[str, Any] = field(default_factory=dict)

    def config_summary(self) -> Dict[str, Any]:
        return {
            "policy": self.policy_factory.__name__ if hasattr(self.policy_factory, "__name__") else "custom",
            "duration": f"{self.duration_seconds}s ceiling",
            "gap": f"{self.gap_seconds}s",
            "endpoint": self.endpoint,
            "find": self.find_target or "(none)",
            **self.extra_config,
        }


async def run_scenario(scenario: Scenario, runs_root: Path) -> Path:
    """Execute one scenario and return the path to its output folder."""
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    slug = f"{stamp}_{scenario.id}_{_slug(scenario.name)}"
    run_dir = runs_root / slug

    with open_run(run_dir) as writer:
        writer.header(scenario.id, scenario.description, scenario.config_summary())

        policy = scenario.policy_factory()

        connect_started = time.monotonic()
        connect_logged = {"done": False}

        def _on_snapshot(snapshot: Any) -> None:
            if not connect_logged["done"]:
                writer.connect(
                    scenario.endpoint,
                    ok=True,
                    milliseconds=(time.monotonic() - connect_started) * 1000.0,
                )
                connect_logged["done"] = True
            writer.snapshot(snapshot)

        def _on_action_request(choice: Any, action_id: str) -> None:
            writer.action_out(
                action=choice.action,
                params=dict(choice.parameters),
                action_id=action_id,
                source=choice.source,
                rationale=choice.rationale,
            )

        bridge = UnityBridge(
            policy=policy,
            config=BridgeConfig(
                endpoint=scenario.endpoint,
                min_seconds_between_actions=scenario.gap_seconds,
                find_target=scenario.find_target,
            ),
            on_snapshot=_on_snapshot,
            on_action_event=_action_event_adapter(writer),
            on_action_request=_on_action_request,
        )

        connect_error = {"msg": None}

        async def _guarded_run() -> None:
            try:
                await bridge.run()
            except Exception as exc:  # noqa: BLE001
                connect_error["msg"] = str(exc)
                writer.note(f"bridge run raised: {exc}")

        async def _stopper() -> None:
            deadline = time.monotonic() + scenario.duration_seconds
            while time.monotonic() < deadline:
                if bridge.metrics.target_found is not None:
                    writer.target_found(bridge.metrics.target_found, bridge.metrics.target_found_distance)
                    await _await_active_terminal(bridge, timeout=4.0)
                    bridge.request_stop()
                    return
                await asyncio.sleep(0.25)
            await _await_active_terminal(bridge, timeout=4.0)
            bridge.request_stop()

        writer.note(f"connecting to {scenario.endpoint} …")
        run_task = asyncio.create_task(_guarded_run())
        stop_task = asyncio.create_task(_stopper())
        await asyncio.gather(run_task, stop_task)

        if connect_error["msg"] is not None:
            writer.connect(scenario.endpoint, ok=False)

        metrics = bridge.metrics.as_dict()
        metrics["wall_time_seconds"] = round(time.monotonic() - connect_started, 2)
        verdict, reason = scenario.verdict(metrics)
        writer.result(metrics, verdict, reason)

    return run_dir


async def _await_active_terminal(bridge: UnityBridge, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        active = bridge.tracker.active
        if active is None or active.is_terminal:
            return
        await asyncio.sleep(0.05)


def _action_event_adapter(writer: PrettyRunWriter):
    """Route ActionRecord updates from the tracker into the pretty writer."""
    def _listener(record: Any) -> None:
        writer.action_event(record.action_id, record.status, record.last_message)
    return _listener


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in text).strip("_")
