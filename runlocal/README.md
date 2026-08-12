# runlocal

One-command startup for the SophiaVerse ↔ OmegaClaw loop, minus Unity.

## Prereqs

- Unity Editor open on `/Users/m4pro/git/sail_redux-Tibex88`, branch
  `feature/game-agent-integration`, with a scene that has the
  `GameStateWebSocketBridge` component active.
- Local venv at `../.venv-bridge`. If missing:
  ```bash
  python3 -m venv ../.venv-bridge
  ../.venv-bridge/bin/pip install websockets openai pytest pytest-asyncio
  ```

## Run

```bash
./start_all.sh
```

This does, in order:

1. Serves the Control Deck static site on `http://127.0.0.1:4173`.
2. Waits up to 15 s for Unity's WebSocket at `127.0.0.1:8765`.
3. Runs the OmegaClaw bridge with the demo sequence
   `RotateRight → RotateLeft → MoveAhead`.

Ctrl-C stops the bridge; a second Ctrl-C stops Control Deck.

Logs land in `runlocal/logs/`.

## Tunables

Every knob is an env var:

| Var | Default | Meaning |
|---|---|---|
| `UNITY_URL` | `ws://127.0.0.1:8765/game/state` | Unity endpoint |
| `CONTROL_DECK_PORT` | `4173` | Control Deck HTTP port |
| `POLICY` | `sequence` | `deterministic` \| `sequence` \| `minimax` |
| `SEQUENCE` | `RotateRight RotateLeft MoveAhead` | Space-separated actions |
| `GAP` | `1.0` | Min seconds between actions |
| `DURATION` | `30` | Bridge runtime (seconds) |
| `WAIT_FOR_UNITY_SECONDS` | `15` | Preflight wait for port 8765 |

Examples:

```bash
# Rotate loop for 10 s
SEQUENCE="RotateRight RotateLeft" DURATION=10 ./start_all.sh

# Try MiniMax (requires ASI_API_KEY exported)
POLICY=minimax DURATION=20 GAP=2 ./start_all.sh
```

## What to look for

- **Unity Editor:** Player rotates and steps forward.
- **Control Deck** (`http://127.0.0.1:4173`, click **Connect**):
  perception panel updates, action lifecycle events appear.
- **This terminal:** `→ Unity: action=…` and `← Unity: id=… status=…` lines
  plus a final metrics summary.
