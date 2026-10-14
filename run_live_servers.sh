#!/usr/bin/env bash
# Starts the two remote A2A agents on local ports and runs the demo against them.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

PYTHON_BIN="python3"
UVICORN_BIN="uvicorn"
if [[ -x "${SCRIPT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python"
  UVICORN_BIN="${SCRIPT_DIR}/.venv/bin/uvicorn"
fi

export OFFLINE_MOCK="${OFFLINE_MOCK:-true}"
export PYTHONWARNINGS="ignore"
export ADK_SUPPRESS_A2A_EXPERIMENTAL_FEATURE_WARNINGS="TRUE"

echo "Starting remote triage agent on http://localhost:8011"
"${UVICORN_BIN}" --app-dir concierge_a2ui_agent remote_a2ui_agents:agent1_app \
  --host localhost --port 8011 --log-level warning &
PID1=$!

echo "Starting remote scheduling agent on http://localhost:8012"
"${UVICORN_BIN}" --app-dir concierge_a2ui_agent remote_a2ui_agents:agent2_app \
  --host localhost --port 8012 --log-level warning &
PID2=$!

cleanup() {
  kill "${PID1}" "${PID2}" 2>/dev/null || true
}
trap cleanup EXIT

sleep 2
"${PYTHON_BIN}" run_demo.py --live-http --offline-mock
