"""CLI entry point: `python -m bridge --policy {deterministic|minimax|sequence}`."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import List, Optional

from .policy import Choice, DeterministicPolicy, MiniMaxPolicy, Policy, ScriptedPolicy
from .sophiaverse_bridge import DEFAULT_ENDPOINT, BridgeConfig, UnityBridge


def _load_use_minimax():
    """Return a callable ``chat_fn(prompt) -> str`` backed by MiniMax on ASI Cloud.

    Prefers OmegaClaw's own ``useMiniMax`` helper when available (older branch
    layout); otherwise builds a minimal OpenAI-compatible client here so the
    bridge stays usable on the canonical OmegaClaw ``main`` layout where the
    provider plugin architecture is in charge.
    """
    import importlib
    import os
    import pathlib
    import sys

    # Only make providers a package via the repo root — NEVER put providers/
    # itself on sys.path, or providers/openai.py will shadow the real openai
    # package.
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)

    for module_path in ("providers.lib_llm_ext", "lib_llm_ext"):
        try:
            module = importlib.import_module(module_path)
        except Exception:  # noqa: BLE001
            continue
        fn = getattr(module, "useMiniMax", None)
        if callable(fn):
            return fn

    # Fallback: self-contained MiniMax caller.
    try:
        import openai
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("openai package is required for --policy minimax") from exc

    api_key = os.environ.get("ASI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ASI_API_KEY is not set")

    client = openai.OpenAI(
        api_key=api_key,
        base_url=os.environ.get("ASI_BASE_URL", "https://inference.asicloud.cudos.org/v1"),
    )
    model = os.environ.get("MINIMAX_MODEL", "minimax/minimax-m2.7")

    def _chat(prompt: str) -> str:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=int(os.environ.get("MINIMAX_MAX_TOKENS", "6000")),
        )
        return (response.choices[0].message.content or "").strip()

    return _chat


def _build_policy(name: str, sequence: Optional[List[str]]) -> Policy:
    if name == "deterministic":
        return DeterministicPolicy(sequence)
    if name == "sequence":
        if not sequence:
            raise SystemExit("--sequence is required for policy=sequence")
        return ScriptedPolicy([_choice_for(action) for action in sequence])
    if name == "minimax":
        try:
            useMiniMax = _load_use_minimax()
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"minimax policy unavailable: {exc}") from exc
        if os.environ.get("ASI_API_KEY", "") == "":
            raise SystemExit("ASI_API_KEY is not set; cannot use MiniMax policy")
        return MiniMaxPolicy(chat_fn=useMiniMax)
    raise SystemExit(f"Unknown policy: {name}")


def _choice_for(action: str) -> Choice:
    if action == "MoveAhead":
        return Choice(action="MoveAhead", parameters={"Distance": 0.3}, source="sequence")
    return Choice(action=action, parameters={}, source="sequence")


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )


async def _run(bridge: UnityBridge, duration: Optional[float], policy: Policy) -> None:
    scripted = policy if isinstance(policy, ScriptedPolicy) else None

    async def _stopper() -> None:
        deadline = None if duration is None else asyncio.get_event_loop().time() + duration
        while True:
            await asyncio.sleep(0.25)
            if deadline is not None and asyncio.get_event_loop().time() >= deadline:
                bridge.request_stop()
                return
            if scripted is not None and scripted.remaining == 0:
                active = bridge.tracker.active
                if active is None or active.is_terminal:
                    # Give Unity a moment to send the final result, then stop.
                    await asyncio.sleep(0.5)
                    bridge.request_stop()
                    return

    await asyncio.gather(bridge.run(), _stopper())


def main() -> int:
    parser = argparse.ArgumentParser(description="OmegaClaw ↔ Unity SophiaVerse bridge")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT,
                        help=f"WebSocket URL (default: {DEFAULT_ENDPOINT})")
    parser.add_argument("--policy", choices=["deterministic", "sequence", "minimax"],
                        default="deterministic")
    parser.add_argument("--sequence", nargs="*", default=None,
                        help="Ordered actions for sequence/deterministic policy")
    parser.add_argument("--action-timeout", type=float, default=15.0)
    parser.add_argument("--gap", type=float, default=0.5,
                        help="Minimum seconds between action requests")
    parser.add_argument("--duration", type=float, default=None,
                        help="Optional runtime limit in seconds")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    _configure_logging(args.verbose)
    policy = _build_policy(args.policy, args.sequence)
    config = BridgeConfig(
        endpoint=args.endpoint,
        action_timeout_seconds=args.action_timeout,
        min_seconds_between_actions=args.gap,
    )
    bridge = UnityBridge(
        policy=policy,
        config=config,
        on_snapshot=lambda snap: logging.getLogger("bridge").info(
            "snapshot: player_pos=%s advertised=%s",
            snap.player_status.get("Position"),
            snap.player_actions.flatten(),
        ),
        on_action_event=lambda rec: logging.getLogger("bridge").info(
            "lifecycle: %s → %s (%s)", rec.action_id, rec.status, rec.last_message,
        ),
    )
    try:
        asyncio.run(_run(bridge, args.duration, policy))
    except KeyboardInterrupt:
        pass
    finally:
        print(json.dumps({"metrics": bridge.metrics.as_dict()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
