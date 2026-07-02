#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${HOME}/.config/agora_ui_runtime.env"
PYTHON_BIN="${PYTHON_BIN:-python3}"

TARGET_DIR="$ROOT_DIR/output"

CONFIG_FILE="${TARGET_DIR}/world_config.json"
SCENARIO_DIR="${TARGET_DIR}/scenario"

GENERATED_REVISION="panjiayuan_run2"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  source "${ENV_FILE}"
  set +a
fi

echo "Launching custom world batch for revision: ${GENERATED_REVISION}"
echo "Config: ${CONFIG_FILE}"
echo "Scenario: ${SCENARIO_DIR}"

exec "${PYTHON_BIN}" "${ROOT_DIR}/asset_pipeline/generate_guild_asset_set.py" \
  --config "${CONFIG_FILE}" \
  --scenario-dir "${SCENARIO_DIR}" \
  --revision "${GENERATED_REVISION}" \
  --all-active-agents
