#!/usr/bin/env bash
# Deploys concierge_a2ui_agent to Vertex AI Agent Engine with Cloud Trace enabled.
#
#   ./deploy_to_agent_engine.sh <project-id> [region] [display-name]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${2:-us-central1}"
DISPLAY_NAME="${3:-concierge-a2ui-patterns-demo}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "usage: $0 <project-id> [region] [display-name]" >&2
  exit 1
fi

ADK_BIN="adk"
if [[ -x "${SCRIPT_DIR}/.venv/bin/adk" ]]; then
  ADK_BIN="${SCRIPT_DIR}/.venv/bin/adk"
fi

echo "Deploying to Agent Engine: project=${PROJECT_ID} region=${REGION} name=${DISPLAY_NAME}"

"${ADK_BIN}" deploy agent_engine \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --display_name="${DISPLAY_NAME}" \
  --description="Multi-agent A2A and A2UI v0.9 patterns demo" \
  --otel_to_cloud \
  "${SCRIPT_DIR}/concierge_a2ui_agent"

echo
echo "Done. Playground: https://console.cloud.google.com/vertex-ai/agents/agent-engines?project=${PROJECT_ID}"
echo "Traces:          https://console.cloud.google.com/traces/list?project=${PROJECT_ID}"
