from __future__ import annotations

import pytest

from bridge.policy import MiniMaxPolicy
from bridge.snapshot import parse_snapshot
from bridge.tests.fake_unity import sample_snapshot


class _FakeChat:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)


@pytest.mark.asyncio
async def test_minimax_extracts_json_from_code_fence():
    chat = _FakeChat([
        '```json\n{"Action": "RotateLeft", "Parameters": {}, '
        '"Rationale": "clear the corridor"}\n```',
    ])
    policy = MiniMaxPolicy(chat_fn=chat)
    snap = parse_snapshot(sample_snapshot())
    choice = await policy.choose(snap)
    assert choice is not None
    assert choice.action == "RotateLeft"
    assert choice.parameters == {}
    assert choice.rationale.startswith("clear")
    assert chat.prompts, "policy must build a prompt"
    assert "AvailableActions.Player" in chat.prompts[0]


@pytest.mark.asyncio
async def test_minimax_moveto_with_target_gets_validated_downstream():
    chat = _FakeChat([
        '{"Action": "MoveTo", "Parameters": {"Target": "Globe"}, "Rationale": "go"}',
    ])
    policy = MiniMaxPolicy(chat_fn=chat)
    snap = parse_snapshot(sample_snapshot())
    choice = await policy.choose(snap)
    assert choice is not None
    assert choice.action == "MoveTo"
    assert choice.parameters == {"Target": "Globe"}


@pytest.mark.asyncio
async def test_minimax_returns_none_for_bad_response():
    chat = _FakeChat(["not-json"])
    policy = MiniMaxPolicy(chat_fn=chat)
    snap = parse_snapshot(sample_snapshot())
    choice = await policy.choose(snap)
    assert choice is None


@pytest.mark.asyncio
async def test_omegasen_prompt_declares_identity_actions_and_rules():
    chat = _FakeChat(['{"Action": "RotateLeft", "Parameters": {}}'])
    policy = MiniMaxPolicy(chat_fn=chat)
    await policy.choose(parse_snapshot(sample_snapshot()))
    prompt = chat.prompts[0]
    assert "OmegaSen" in prompt
    assert "SAIL" in prompt
    assert "distinct from Sen" in prompt
    for name in ("MoveAhead", "MoveBack", "MoveLeft", "MoveRight",
                 "RotateLeft", "RotateRight", "MoveTo", "Interact", "Cancel"):
        assert name in prompt
    assert "AvailableActions.Player" in prompt
    assert "strict JSON" in prompt.lower() or "no code fence" in prompt


@pytest.mark.asyncio
async def test_minimax_rotate_with_degrees_parameter_passes_through():
    chat = _FakeChat(['{"Action": "RotateRight", "Parameters": {"Degrees": 30}}'])
    policy = MiniMaxPolicy(chat_fn=chat)
    choice = await policy.choose(parse_snapshot(sample_snapshot()))
    assert choice is not None
    assert choice.action == "RotateRight"
    assert choice.parameters == {"Degrees": 30}


@pytest.mark.asyncio
async def test_minimax_move_ahead_with_distance_parameter_passes_through():
    chat = _FakeChat(['{"Action": "MoveAhead", "Parameters": {"Distance": 0.4}}'])
    policy = MiniMaxPolicy(chat_fn=chat)
    choice = await policy.choose(parse_snapshot(sample_snapshot()))
    assert choice is not None
    assert choice.action == "MoveAhead"
    assert choice.parameters == {"Distance": 0.4}


@pytest.mark.asyncio
async def test_minimax_empty_object_response_treated_as_skip():
    chat = _FakeChat(['{}'])
    policy = MiniMaxPolicy(chat_fn=chat)
    choice = await policy.choose(parse_snapshot(sample_snapshot()))
    assert choice is None
