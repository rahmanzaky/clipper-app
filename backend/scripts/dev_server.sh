#!/usr/bin/env bash
# Starts the backend with sensible defaults for local development. Re-typing
# `HF_HUB_DISABLE_XET=1 WHISPER_MODEL=small uvicorn api:app --host 127.0.0.1
# --port 8000` from memory every restart is exactly the kind of thing that gets
# forgotten or fat-fingered — this exists so it doesn't have to be.
#
# Usage:
#   ./scripts/dev_server.sh              # fast iteration (small Whisper model)
#   FAST=0 ./scripts/dev_server.sh        # real accuracy (large-v3-turbo, slower)
#   PORT=8001 ./scripts/dev_server.sh     # different port

set -euo pipefail
cd "$(dirname "$0")/.."  # backend/

if [ ! -d "../venv" ]; then
  echo "No venv found at ../venv — run the Setup steps in the README first." >&2
  exit 1
fi
# shellcheck disable=SC1091
source ../venv/bin/activate

FAST="${FAST:-1}"
PORT="${PORT:-8000}"
export HF_HUB_DISABLE_XET=1

if [ "$FAST" = "1" ]; then
  export WHISPER_MODEL="${WHISPER_MODEL:-small}"
  echo "Starting with WHISPER_MODEL=$WHISPER_MODEL (fast iteration — weaker Indonesian accuracy)."
  echo "Use FAST=0 ./scripts/dev_server.sh for large-v3-turbo (real accuracy, slower)."
else
  unset WHISPER_MODEL
  echo "Starting with the default large-v3-turbo model (best bilingual accuracy, slower)."
fi

exec uvicorn api:app --host 127.0.0.1 --port "$PORT"
