#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UI_DIR="${ROOT_DIR}/world_creator_ui"
PORT="${PORT:-8123}"
OUTPUT_PATH="${1:-/tmp/creator_regression.png}"
FIXTURE_NAME="${FIXTURE_NAME:-demo}"
URL="http://127.0.0.1:${PORT}/index.html?fixture=${FIXTURE_NAME}"

if ! command -v firefox >/dev/null 2>&1; then
  echo "firefox is required but was not found in PATH" >&2
  exit 1
fi

SERVER_PID=""

cleanup() {
  if [[ -n "${SERVER_PID}" ]] && kill -0 "${SERVER_PID}" >/dev/null 2>&1; then
    kill "${SERVER_PID}" >/dev/null 2>&1 || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

cd "${UI_DIR}"
python -m http.server "${PORT}" >/tmp/creator_regression_server.log 2>&1 &
SERVER_PID="$!"

for _ in $(seq 1 50); do
  if curl -fsS "http://127.0.0.1:${PORT}/index.html" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

firefox --headless --width 1440 --height 2600 --screenshot "${OUTPUT_PATH}" "${URL}"
echo "creator regression screenshot saved to ${OUTPUT_PATH}"
