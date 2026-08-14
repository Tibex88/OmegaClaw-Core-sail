"""Shared helpers for scenarios that use the MiniMax LLM policy."""
from __future__ import annotations

import os
from typing import Callable, Optional

from bridge.policy import MiniMaxPolicy, Policy


def _load_chat_fn() -> Callable[[str], str]:
    """Import the same MiniMax loader the CLI uses."""
    from bridge.__main__ import _load_use_minimax  # noqa: WPS433
    return _load_use_minimax()


def minimax_policy_factory(goal_text: Optional[str] = None) -> Callable[[], Policy]:
    """Return a factory that builds a MiniMaxPolicy on demand.

    We defer loading until the factory is called so the module can be imported
    without ASI_API_KEY being present (e.g. during pytest collection).
    """
    def _factory() -> Policy:
        if not os.environ.get("ASI_API_KEY"):
            raise RuntimeError("ASI_API_KEY is not set; export it or run experiments/run.sh")
        return MiniMaxPolicy(chat_fn=_load_chat_fn(), goal_text=goal_text)

    _factory.__name__ = "MiniMaxPolicy"
    return _factory
