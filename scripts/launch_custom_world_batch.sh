#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${HOME}/.config/agora_ui_runtime.env"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <path_to_revision_directory> [additional args...]"
    echo "Example: $0 output/world_creator_drafts/creator_20260528_212604_814cbc85/revisions/r001"
    exit 1
fi

TARGET_DIR=$(realpath "$1")
shift

CONFIG_FILE="${TARGET_DIR}/world_config.json"
SCENARIO_DIR="${TARGET_DIR}/scenario"

if [ ! -f "${CONFIG_FILE}" ]; then
    echo "Error: world_config.json not found in ${TARGET_DIR}"
    exit 1
fi

if [ ! -d "${SCENARIO_DIR}" ]; then
    echo "Error: scenario directory not found in ${TARGET_DIR}"
    exit 1
fi

# Extract the draft and revision name from the path to use as the revision alias
# E.g. "creator_20260528_212604_814cbc85" and "r001"
DRAFT_NAME=$(basename "$(dirname "$(dirname "${TARGET_DIR}")")")
REVISION_NAME=$(basename "${TARGET_DIR}")
GENERATED_REVISION="${DRAFT_NAME}_${REVISION_NAME}_$(date -u +%Y%m%d_%H%M%S)"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

echo "Launching custom world batch for revision: ${GENERATED_REVISION}"
echo "Config: ${CONFIG_FILE}"
echo "Scenario: ${SCENARIO_DIR}"

exec "${PYTHON_BIN}" "${ROOT_DIR}/asset_pipeline/generate_world_asset_set.py" \
  --config "${CONFIG_FILE}" \
  --scenario-dir "${SCENARIO_DIR}" \
  --revision "${GENERATED_REVISION}" \
  --all-active-agents \
  --update-current-alias \
  "$@"
