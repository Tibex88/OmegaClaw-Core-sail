#!/usr/bin/env bash
# Start Control Deck and the OmegaClaw ↔ Unity bridge together.
# Unity must already be running (Play mode) at ws://127.0.0.1:8765/game/state.
#
# Ctrl-C to stop everything.

set -euo pipefail

# Paths (absolute so this script works from anywhere)
OMEGA_DIR="/Users/m4pro/git/OmegaClaw-Core-sail"
CONTROL_DECK_DIR="/Users/m4pro/git/sophiaverse-control-deck"
VENV_PYTHON="${OMEGA_DIR}/.venv-bridge/bin/python"
LOG_DIR="${OMEGA_DIR}/runlocal/logs"

# Tunables (override via environment)
UNITY_URL="${UNITY_URL:-ws://127.0.0.1:8765/game/state}"
CONTROL_DECK_PORT="${CONTROL_DECK_PORT:-4173}"
POLICY="${POLICY:-sequence}"
SEQUENCE="${SEQUENCE:-RotateRight RotateLeft MoveAhead}"
GAP="${GAP:-1.0}"
DURATION="${DURATION:-30}"
WAIT_FOR_UNITY_SECONDS="${WAIT_FOR_UNITY_SECONDS:-15}"

mkdir -p "${LOG_DIR}"
BRIDGE_LOG="${LOG_DIR}/bridge.log"
DECK_LOG="${LOG_DIR}/control_deck.log"

# --- preflight ---------------------------------------------------------------
if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "!! Missing venv at ${VENV_PYTHON}"
    echo "   Run:  python3 -m venv ${OMEGA_DIR}/.venv-bridge \\"
    echo "         && ${OMEGA_DIR}/.venv-bridge/bin/pip install websockets openai pytest pytest-asyncio"
    exit 1
fi

if [[ ! -d "${CONTROL_DECK_DIR}" ]]; then
    echo "!! Control Deck missing at ${CONTROL_DECK_DIR}"
    exit 1
fi

# --- process bookkeeping ------------------------------------------------------
PIDS=()

cleanup() {
    echo ""
    echo "== stopping (Ctrl-C) =="
    for pid in "${PIDS[@]:-}"; do
        if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
            echo "   killing pid ${pid}"
            kill "${pid}" 2>/dev/null || true
        fi
    done
    wait 2>/dev/null || true
    echo "== stopped =="
}
trap cleanup EXIT INT TERM

# --- 1. Control Deck ---------------------------------------------------------
echo "== starting Control Deck on http://127.0.0.1:${CONTROL_DECK_PORT} =="
(
    cd "${CONTROL_DECK_DIR}"
    exec python3 -m http.server "${CONTROL_DECK_PORT}"
) > "${DECK_LOG}" 2>&1 &
DECK_PID=$!
PIDS+=("${DECK_PID}")
echo "   pid=${DECK_PID}  log=${DECK_LOG}"
sleep 0.5

# --- 2. Wait for Unity -------------------------------------------------------
echo "== waiting up to ${WAIT_FOR_UNITY_SECONDS}s for Unity at ${UNITY_URL} =="
UNITY_HOST=$(echo "${UNITY_URL}" | sed -E 's#^ws://([^:/]+):.*#\1#')
UNITY_PORT=$(echo "${UNITY_URL}" | sed -E 's#^ws://[^:]+:([0-9]+).*#\1#')
UNITY_UP=0
for _ in $(seq 1 "${WAIT_FOR_UNITY_SECONDS}"); do
    if nc -z "${UNITY_HOST}" "${UNITY_PORT}" 2>/dev/null; then
        UNITY_UP=1
        break
    fi
    sleep 1
done

if [[ "${UNITY_UP}" -eq 0 ]]; then
    echo "!! Unity is not listening on ${UNITY_HOST}:${UNITY_PORT}"
    echo "   Enter Play mode in Unity, then rerun this script."
    exit 1
fi
echo "== Unity is up =="

# --- 3. Bridge --------------------------------------------------------------
echo "== starting OmegaClaw bridge  (policy=${POLICY}) =="
echo "   endpoint=${UNITY_URL}"
echo "   sequence=${SEQUENCE}"
echo "   gap=${GAP}s  duration=${DURATION}s"
echo "   log=${BRIDGE_LOG}"

# Run bridge in foreground so Ctrl-C reaches it and we see its transcript.
# Also tee to the log file for later review.
# The `bridge` package lives under OMEGA_DIR, so run from there.
# shellcheck disable=SC2086
(
    cd "${OMEGA_DIR}"
    "${VENV_PYTHON}" -m bridge \
        --endpoint "${UNITY_URL}" \
        --policy "${POLICY}" \
        --sequence ${SEQUENCE} \
        --gap "${GAP}" \
        --duration "${DURATION}" \
        --verbose
) 2>&1 | tee "${BRIDGE_LOG}"

echo ""
echo "== bridge exited =="
echo "   open http://127.0.0.1:${CONTROL_DECK_PORT} to inspect Control Deck (still running)"
echo "   Ctrl-C to stop Control Deck"

# Keep Control Deck alive until user closes.
wait "${DECK_PID}"
