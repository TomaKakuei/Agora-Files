#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PY_BIN="${PY_BIN:-python3}"
ENV_FILE="$ROOT_DIR/.env"
OUTPUT_ROOT="${REPO_ROOT}/output/replay_runs"
SOURCE_RUN="${OUTPUT_ROOT}/gallery_multimodal_40a_40r_act025_fix_20260504_01"
SOURCE_SCENARIO="${SOURCE_RUN}/run_inputs/scenario"
SOURCE_PROFILE_CACHE="${SOURCE_RUN}/agent_profile_api_cache"
TEXT_TEMPLATE="${REPO_ROOT}/sample_json/projections/art_gallery_text_only.json"
MULTI_TEMPLATE="${REPO_ROOT}/sample_json/projections/art_gallery_multimodal.json"

if [[ ! -x "${PY_BIN}" ]]; then
  echo "python not found: ${PY_BIN}" >&2
  exit 2
fi
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "runtime env file not found: ${ENV_FILE}" >&2
  exit 2
fi
if [[ ! -d "${SOURCE_SCENARIO}" ]]; then
  echo "source scenario not found: ${SOURCE_SCENARIO}" >&2
  exit 2
fi
if [[ ! -d "${SOURCE_PROFILE_CACHE}" ]]; then
  echo "source profile cache not found: ${SOURCE_PROFILE_CACHE}" >&2
  exit 2
fi

. "${ENV_FILE}"
export MKL_SERVICE_FORCE_INTEL=1
export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"

STAMP="${STAMP:-$(date -u +%Y%m%d_%H%M%S)}"
TEXT_RUN_ID="${TEXT_RUN_ID:-gallery_textonly_40a_40r_act025_vertex_noll_${STAMP}}"
MULTI_RUN_ID="${MULTI_RUN_ID:-gallery_multimodal_40a_40r_act025_flex_noll_${STAMP}}"

prepare_run() {
  local run_id="$1"
  local template_path="$2"
  local run_dir="${OUTPUT_ROOT}/${run_id}"
  local run_inputs_dir="${run_dir}/run_inputs"
  local runtime_dir="${run_dir}/runtime"
  if [[ -e "${run_dir}" ]]; then
    echo "run dir already exists: ${run_dir}" >&2
    exit 2
  fi
  mkdir -p "${run_inputs_dir}" "${runtime_dir}"
  cp "${template_path}" "${run_inputs_dir}/world_config.json"
  cp -a "${SOURCE_SCENARIO}" "${run_inputs_dir}/scenario"
}

run_case() {
  local run_id="$1"
  local log_path="${OUTPUT_ROOT}/${run_id}/runtime/launcher.log"
  local config_path="${OUTPUT_ROOT}/${run_id}/run_inputs/world_config.json"
  local scenario_dir="${OUTPUT_ROOT}/${run_id}/run_inputs/scenario"
  "${PY_BIN}" -m agora_ui.run_interaction_simulation \
    --config "${config_path}" \
    --scenario-dir "${scenario_dir}" \
    --output-dir "${OUTPUT_ROOT}" \
    --run-id "${run_id}" \
    --rounds 40 \
    --activation 0.25 \
    --seed 1201 \
    --reuse-agent-profile-cache "${SOURCE_PROFILE_CACHE}" \
    >> "${log_path}" 2>&1
}

assert_ok_manifest() {
  local run_id="$1"
  local manifest_path="${OUTPUT_ROOT}/${run_id}/final_manifest.json"
  if [[ ! -f "${manifest_path}" ]]; then
    echo "missing final manifest: ${manifest_path}" >&2
    exit 3
  fi
  local status
  status="$("${PY_BIN}" -c 'import json,sys; print(json.load(open(sys.argv[1], "r", encoding="utf-8")).get("status",""))' "${manifest_path}")"
  if [[ "${status}" != "ok" ]]; then
    echo "run did not finish cleanly: ${run_id} status=${status}" >&2
    exit 4
  fi
}

prepare_run "${TEXT_RUN_ID}" "${TEXT_TEMPLATE}"
prepare_run "${MULTI_RUN_ID}" "${MULTI_TEMPLATE}"

echo "[QUEUE] text_only=${TEXT_RUN_ID}"
run_case "${TEXT_RUN_ID}"
assert_ok_manifest "${TEXT_RUN_ID}"

echo "[QUEUE] multimodal=${MULTI_RUN_ID}"
run_case "${MULTI_RUN_ID}"
assert_ok_manifest "${MULTI_RUN_ID}"

echo "[DONE] text_only=${TEXT_RUN_ID} multimodal=${MULTI_RUN_ID}"
