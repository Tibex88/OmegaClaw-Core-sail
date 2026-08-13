#!/usr/bin/env bash
# Thin wrapper around `python -m experiments.run` that uses the local venv.
set -euo pipefail

OMEGA_DIR="/Users/m4pro/git/OmegaClaw-Core-sail"
VENV_PYTHON="${OMEGA_DIR}/.venv-bridge/bin/python"

if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "!! Missing venv at ${VENV_PYTHON}"
    echo "   python3 -m venv ${OMEGA_DIR}/.venv-bridge && \\"
    echo "   ${OMEGA_DIR}/.venv-bridge/bin/pip install websockets openai pyyaml pytest pytest-asyncio"
    exit 1
fi

# ASI_API_KEY for LLM scenarios: load from keys/minimax if present.
KEY_FILE="${OMEGA_DIR}/keys/minimax"
if [[ -z "${ASI_API_KEY:-}" && -r "${KEY_FILE}" ]]; then
    ASI_API_KEY="$(tr -d '[:space:]' < "${KEY_FILE}")"
    export ASI_API_KEY
fi

cd "${OMEGA_DIR}"
exec "${VENV_PYTHON}" -m experiments.run "$@"
