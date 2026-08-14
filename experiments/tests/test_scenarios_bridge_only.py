"""Structural checks for all 10 scenarios.

Every scenario now uses MiniMax, so we can't drive them end-to-end from
pytest without hitting the real LLM. These tests verify:

- Each s##_*.py module exposes a valid Scenario object.
- Each scenario has a working verdict function and reasonable config.
- The policy_factory can be inspected without invoking the LLM.
"""
from __future__ import annotations

from experiments.scenarios import (
    s01_deterministic_smoke,
    s02_cancel_mid_flight,
    s03_moveto_navmesh,
    s04_unadvertised_action_rejected,
    s05_one_in_flight_enforcement,
    s06_search_existing_target,
    s07_search_missing_target_crixi,
    s08_llm_free_play_60s,
    s09_llm_search_crixi_180s,
    s10_llm_navigate_to_globe,
)


ALL_MODULES = (
    s01_deterministic_smoke,
    s02_cancel_mid_flight,
    s03_moveto_navmesh,
    s04_unadvertised_action_rejected,
    s05_one_in_flight_enforcement,
    s06_search_existing_target,
    s07_search_missing_target_crixi,
    s08_llm_free_play_60s,
    s09_llm_search_crixi_180s,
    s10_llm_navigate_to_globe,
)


def test_all_scenarios_expose_scenario_object() -> None:
    for module in ALL_MODULES:
        scenario = module.SCENARIO
        assert scenario.id.startswith("S")
        assert scenario.name
        assert scenario.description
        assert callable(scenario.policy_factory)
        assert scenario.duration_seconds > 0
        assert callable(scenario.verdict)


def test_all_scenarios_have_unique_ids() -> None:
    ids = [m.SCENARIO.id for m in ALL_MODULES]
    assert len(ids) == len(set(ids))
    assert sorted(ids) == [f"S{n:02d}" for n in range(1, 11)]


def test_verdict_functions_return_two_string_tuples() -> None:
    dummy_metrics = {
        "snapshots_received": 10,
        "actions_requested": 3,
        "actions_completed": 3,
        "actions_rejected_by_bridge": 0,
        "actions_rejected_by_unity": 0,
        "actions_cancelled": 0,
        "actions_failed": 0,
        "actions_timed_out": 0,
        "target_found": None,
        "target_found_distance": None,
        "wall_time_seconds": 5.0,
    }
    for module in ALL_MODULES:
        verdict, reason = module.SCENARIO.verdict(dummy_metrics)
        assert isinstance(verdict, str) and verdict
        assert isinstance(reason, str) and reason


def test_search_scenarios_have_find_target() -> None:
    assert s06_search_existing_target.SCENARIO.find_target == "Interactable"
    assert s07_search_missing_target_crixi.SCENARIO.find_target == "Crixi"
    assert s09_llm_search_crixi_180s.SCENARIO.find_target == "Crixi"
