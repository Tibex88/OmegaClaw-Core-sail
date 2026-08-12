from __future__ import annotations

import pytest

from bridge.snapshot import SnapshotError, parse_snapshot
from bridge.tests.fake_unity import sample_snapshot


def test_parses_schema_2_2_snapshot():
    snap = parse_snapshot(sample_snapshot())
    assert snap.schema_version == "2.2"
    assert snap.controlled_entity == "Player"
    assert snap.player_actions.primitives == ["MoveAhead", "RotateLeft", "RotateRight"]
    assert snap.player_actions.move_to_targets == ["Globe"]
    assert snap.player_perception["ObservationMode"] == "raycast_metadata"
    assert snap.player_perception["VisibleEntities"][0]["Name"] == "Globe"


def test_rejects_wrong_type():
    payload = sample_snapshot()
    payload["Type"] = "game.other"
    with pytest.raises(SnapshotError):
        parse_snapshot(payload)


def test_rejects_unsupported_schema():
    payload = sample_snapshot()
    payload["SchemaVersion"] = "9.0"
    with pytest.raises(SnapshotError):
        parse_snapshot(payload)


def test_rejects_missing_available_actions():
    payload = sample_snapshot()
    payload["Payload"].pop("AvailableActions")
    with pytest.raises(SnapshotError):
        parse_snapshot(payload)


def test_rejects_missing_perceptions():
    payload = sample_snapshot()
    payload["Payload"]["UInput"].pop("Perceptions")
    with pytest.raises(SnapshotError):
        parse_snapshot(payload)


def test_available_actions_has_action():
    snap = parse_snapshot(sample_snapshot())
    aa = snap.player_actions
    assert aa.has_action("MoveAhead")
    assert aa.has_action("MoveTo", "Globe")
    assert not aa.has_action("MoveTo", "Mars")
    assert not aa.has_action("Fly")
