"""SAIL game-state WebSocket channel for the MeTTa loop.

Connects to Unity's /game/state endpoint (schema 2.2). Snapshots become the
"input" the MeTTa loop reacts to via ``receive()``. Actions are dispatched
through skills defined in ``src/sail_skills.metta``, which call
``send_action(...)`` here to place a validated ``game.action.request`` on the
wire. ``send()`` is a status logger; there is no human at the other end.

State is thread-safe: a background thread owns the WebSocket, updates the
latest snapshot and lifecycle events under a lock, and the MeTTa side reads
via the accessor functions below.
"""

import json
import logging
import os
import random
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.logger import get_logger
try:
    import channels
except ModuleNotFoundError:
    import src.channels as channels
from config import config_get_by_key

logger = get_logger(__name__)

DEFAULT_ENDPOINT = "ws://127.0.0.1:8765/game/state"
SUPPORTED_SCHEMA = "2.2"
PLAYER_ACTOR = "Player"
_TERMINAL = {"completed", "failed", "cancelled", "rejected"}

_state_lock = threading.Lock()
_send_lock = threading.Lock()
_running = False
_thread: Optional[threading.Thread] = None
_ws = None
_ws_url = DEFAULT_ENDPOINT
_connected = False

_last_snapshot: Optional[Dict[str, Any]] = None
_last_snapshot_epoch: int = 0
_last_snapshot_delivered: int = 0
_action_records: Dict[str, Dict[str, Any]] = {}
_action_events: deque = deque(maxlen=64)
_active_action_id: Optional[str] = None
_last_submitted_action_id: Optional[str] = None


def _connect_client(ws_url: str):
    from websockets.sync.client import connect
    # ping_interval=None disables client-side keepalive; Unity emits a
    # snapshot every ~1s, which keeps the socket live without needing pings.
    return connect(
        ws_url,
        open_timeout=15,
        close_timeout=5,
        ping_interval=None,
        max_size=1 * 1024 * 1024,
    )


def _set_connection(ws) -> None:
    global _ws, _connected
    with _state_lock:
        _ws = ws
        _connected = True


def _clear_connection(ws=None) -> None:
    global _ws, _connected
    with _state_lock:
        if ws is not None and _ws is not ws:
            return
        _ws = None
        _connected = False


def _summarise_snapshot(snapshot: Dict[str, Any]) -> str:
    """Compact text summary safe to feed to an LLM inside a MeTTa prompt."""
    payload = snapshot.get("Payload") or {}
    u_input = payload.get("UInput") or {}
    perceptions = u_input.get("Perceptions") or {}
    player_percept = perceptions.get(PLAYER_ACTOR) or {}
    status = u_input.get("PlayerStatus") or {}
    available = (payload.get("AvailableActions") or {}).get(PLAYER_ACTOR) or {}

    visible = list((player_percept.get("VisibleEntities") or [])[:6])
    visible_short = [
        {
            "n": e.get("Name"),
            "k": e.get("Kinds", []),
            "d": round(float(e.get("Distance") or 0.0), 2),
            "a": round(float(e.get("AngleDegrees") or 0.0), 1),
            "acts": e.get("AvailableActions", []),
        }
        for e in visible
    ]
    summary = {
        "schema": snapshot.get("SchemaVersion"),
        "controlled": payload.get("ControlledEntity"),
        "player": {
            "pos": status.get("Position"),
            "fwd": status.get("Forward"),
            "moving": status.get("IsMoving"),
        },
        "visible": visible_short,
        "actions": {
            "Primitive": available.get("Primitive", []),
            "MoveTo": available.get("MoveTo", []),
            "Interact": available.get("Interact", []),
        },
        "active_action": _active_action_id,
    }
    return "SNAPSHOT " + json.dumps(summary, ensure_ascii=False, separators=(",", ":"))


def _validate_action(action: str, params: Dict[str, Any]) -> Tuple[bool, str]:
    """Check the action against the latest snapshot's AvailableActions.Player."""
    if action == "Cancel":
        return True, ""
    with _state_lock:
        snap = _last_snapshot
    if snap is None:
        return False, "no snapshot received yet"
    payload = snap.get("Payload") or {}
    advertised = (payload.get("AvailableActions") or {}).get(PLAYER_ACTOR) or {}
    primitives = advertised.get("Primitive") or []
    move_to = advertised.get("MoveTo") or []

    if action == "MoveTo":
        target = params.get("Target")
        if not isinstance(target, str) or target not in move_to:
            return False, f"MoveTo target {target!r} not in advertised list {move_to}"
        return True, ""

    if action in primitives:
        return True, ""

    other = {k: v for k, v in advertised.items() if k not in {"Primitive", "MoveTo"}}
    if action in other:
        return True, ""
    return False, f"action {action!r} not in AvailableActions.Player"


def _handle_frame(raw_message) -> None:
    global _last_snapshot, _last_snapshot_epoch, _active_action_id
    if isinstance(raw_message, bytes):
        raw_message = raw_message.decode("utf-8", errors="ignore")
    try:
        frame = json.loads(raw_message)
    except json.JSONDecodeError:
        logger.warning("Ignoring non-JSON frame from Unity")
        return
    if not isinstance(frame, dict):
        return

    if frame.get("Type") == "game.state.snapshot":
        if frame.get("SchemaVersion") != SUPPORTED_SCHEMA:
            logger.warning("Ignoring snapshot with unsupported schema %s", frame.get("SchemaVersion"))
            return
        with _state_lock:
            _last_snapshot = frame
            _last_snapshot_epoch += 1
        return

    action_id = frame.get("ActionId")
    status = frame.get("Status")
    if action_id and status:
        status = status.lower()
        with _state_lock:
            record = _action_records.get(action_id)
            if record is not None:
                record["status"] = status
                record["message"] = frame.get("Message", "")
                record["history"].append(status)
                if status in _TERMINAL and _active_action_id == action_id:
                    _active_action_id = None
            _action_events.append({
                "id": action_id,
                "action": frame.get("Action"),
                "status": status,
                "message": frame.get("Message", ""),
                "ts": time.monotonic(),
            })
        return

    logger.debug("Ignoring unknown Unity frame: %s", frame.get("Type"))


def _listen_loop() -> None:
    backoff = 1.0
    while _running:
        active_ws = None
        try:
            with _connect_client(_ws_url) as ws:
                active_ws = ws
                _set_connection(ws)
                logger.info("Connected to Unity at %s", _ws_url)
                backoff = 1.0
                while _running:
                    raw = ws.recv()
                    if raw is None:
                        raise RuntimeError("Unity closed the connection")
                    _handle_frame(raw)
        except Exception as exc:  # noqa: BLE001
            _clear_connection(active_ws)
            active_ws = None
            if not _running:
                break
            delay = min(backoff, 30.0)
            delay += random.uniform(0.0, delay * 0.2)
            logger.warning("Unity connection error: %s. Reconnecting in %.1fs", exc, delay)
            time.sleep(delay)
            backoff = min(backoff * 2.0, 30.0)
        finally:
            _clear_connection(active_ws)
    logger.info("game_ws listener stopped")


def start_game_ws(ws_url: Optional[str] = None) -> Optional[threading.Thread]:
    global _running, _thread, _ws_url
    _ws_url = str(ws_url or os.environ.get("UNITY_GAME_STATE_URL") or DEFAULT_ENDPOINT)
    try:
        from websockets.sync.client import connect  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        logger.exception("game_ws channel disabled: websockets not installed: %s", exc)
        return None
    _running = True
    _thread = threading.Thread(target=_listen_loop, daemon=True, name="game-ws-channel")
    _thread.start()
    return _thread


def stop_game_ws() -> None:
    global _running
    _running = False
    with _state_lock:
        active = _ws
    if active is None:
        return
    try:
        active.close()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error closing game_ws: %s", exc)


def getLastMessage() -> str:
    """MeTTa `receive()` — return a compact snapshot summary when a new one
    has arrived, otherwise the empty string so the loop stays quiet.
    """
    global _last_snapshot_delivered
    with _state_lock:
        snapshot = _last_snapshot
        epoch = _last_snapshot_epoch
        already = _last_snapshot_delivered
    if snapshot is None or epoch == already:
        return ""
    with _state_lock:
        _last_snapshot_delivered = epoch
    return _summarise_snapshot(snapshot)


def send_message(text: str) -> None:
    """MeTTa `send()` — no human is on the other side. Log for observability."""
    message = str(text or "").strip()
    if not message:
        return
    logger.info("OmegaSen says: %s", message)


def send_action(action: str, parameters: Optional[Dict[str, Any]] = None) -> str:
    """Emit a game.action.request over the WebSocket. Returns a short status
    string suitable for logging by MeTTa skills.
    """
    global _active_action_id, _last_submitted_action_id
    parameters = dict(parameters or {})

    ok, reason = _validate_action(action, parameters)
    if not ok:
        return f"REJECTED_LOCALLY: {reason}"

    with _state_lock:
        if action != "Cancel" and _active_action_id is not None:
            return f"BUSY: {_active_action_id} is still in flight"
        active_ws = _ws
        connected = _connected

    if not connected or active_ws is None:
        return "DISCONNECTED: Unity WebSocket is not connected"

    action_id = f"omegasen-{uuid.uuid4().hex[:12]}"
    request = {
        "Type": "game.action.request",
        "ActionId": action_id,
        "Actor": PLAYER_ACTOR,
        "Action": action,
        "Parameters": parameters,
    }

    with _state_lock:
        _action_records[action_id] = {
            "action": action,
            "parameters": parameters,
            "status": "pending",
            "message": "",
            "history": [],
            "submitted_at": time.monotonic(),
        }
        if action != "Cancel":
            _active_action_id = action_id
        _last_submitted_action_id = action_id

    try:
        with _send_lock:
            active_ws.send(json.dumps(request))
    except Exception as exc:  # noqa: BLE001
        with _state_lock:
            _action_records[action_id]["status"] = "failed"
            _action_records[action_id]["message"] = f"send failed: {exc}"
            if _active_action_id == action_id:
                _active_action_id = None
        logger.exception("send_action failed: %s", exc)
        return f"SEND_FAILED: {exc}"

    return f"SENT: id={action_id} action={action}"


def wait_for_terminal(timeout_seconds: float = 15.0) -> str:
    """Block up to ``timeout_seconds`` waiting for the last submitted action
    to reach a terminal status. Returns the terminal status string, or
    ``"idle"`` when no action has ever been submitted.
    """
    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    while time.monotonic() < deadline:
        with _state_lock:
            target_id = _active_action_id or _last_submitted_action_id
            record = _action_records.get(target_id) if target_id else None
        if target_id is None:
            return "idle"
        if record is not None and record.get("status") in _TERMINAL:
            return str(record.get("status") or "unknown")
        time.sleep(0.05)
    return "timeout"


def perceive() -> str:
    """Skill accessor: return the current snapshot summary regardless of
    whether the MeTTa loop has already consumed it.
    """
    with _state_lock:
        snapshot = _last_snapshot
    if snapshot is None:
        return "NO_SNAPSHOT"
    return _summarise_snapshot(snapshot)


class GameWSChannel(channels.CommChannel):

    def start(self) -> None:
        start_game_ws(config_get_by_key("UNITY_GAME_STATE_URL", DEFAULT_ENDPOINT))

    def stop(self) -> None:
        stop_game_ws()

    def receive(self) -> str:
        return getLastMessage()

    def send(self, message: str) -> None:
        send_message(message)


def loadOmegaClawPlugin() -> None:
    channels.registerCommChannel("game_ws", GameWSChannel())
