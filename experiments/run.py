"""Run one or more scenarios and produce per-run folders under experiments/runs/.

Usage:
    python -m experiments.run                    # run all registered scenarios
    python -m experiments.run S01                # run one
    python -m experiments.run S01 S03 S07        # run a subset
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import pkgutil
import sys
from pathlib import Path
from typing import Dict, List

from experiments.scenarios import base as _base
from experiments.scenarios.base import Scenario, run_scenario


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = REPO_ROOT / "experiments" / "runs"


def _discover() -> Dict[str, Scenario]:
    """Import every experiments.scenarios.s*_* module and collect SCENARIO."""
    import experiments.scenarios as pkg
    registry: Dict[str, Scenario] = {}
    for info in pkgutil.iter_modules(pkg.__path__):
        if not info.name.startswith("s"):
            continue
        module = importlib.import_module(f"experiments.scenarios.{info.name}")
        scenario = getattr(module, "SCENARIO", None)
        if scenario is not None:
            registry[scenario.id] = scenario
    return registry


def _select(registry: Dict[str, Scenario], requested: List[str]) -> List[Scenario]:
    if not requested or requested == ["all"]:
        return [registry[k] for k in sorted(registry)]
    picked = []
    for wanted in requested:
        if wanted not in registry:
            available = ", ".join(sorted(registry))
            raise SystemExit(f"Unknown scenario {wanted!r}. Available: {available}")
        picked.append(registry[wanted])
    return picked


async def _amain(ids: List[str]) -> int:
    registry = _discover()
    scenarios = _select(registry, ids)
    print(f"Scheduled {len(scenarios)} scenario(s):\n")
    for s in scenarios:
        print(f"  {s.id}  {s.name}")
        print(f"        {s.description}")
    print()
    for i, scenario in enumerate(scenarios, start=1):
        print("─" * 72)
        print(f"[{i}/{len(scenarios)}] {scenario.id}  {scenario.name}")
        print(f"          {scenario.description}")
        print(f"          endpoint={scenario.endpoint}  duration≤{scenario.duration_seconds:.0f}s  gap={scenario.gap_seconds}s"
              + (f"  find={scenario.find_target}" if scenario.find_target else ""))
        run_dir = await run_scenario(scenario, RUNS_ROOT)
        verdict_line = _read_verdict(run_dir)
        print(f"     →    {verdict_line}")
        print(f"          {run_dir}")
    print("─" * 72)
    return 0


def _read_verdict(run_dir: Path) -> str:
    import json
    metrics = json.loads((run_dir / "metrics.json").read_text())
    return f"{metrics.get('verdict', '?')}  ({metrics.get('verdict_reason', '')})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OmegaSen experiment scenarios.")
    parser.add_argument("ids", nargs="*", help="Scenario IDs (S01, S02, ...) or 'all'")
    args = parser.parse_args()
    return asyncio.run(_amain(args.ids))


if __name__ == "__main__":
    sys.exit(main())
