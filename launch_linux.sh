#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -f .venv/bin/activate ]]; then
  echo 'Run Linux installation instructions in README.md first.'
  exit 1
fi
source .venv/bin/activate
exec python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
