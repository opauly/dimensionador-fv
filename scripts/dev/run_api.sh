#!/bin/bash
# Runs vrm_api (FastAPI) in the foreground. Called by start_vrm_monitor.command
# (each service gets its own Terminal window so logs/Ctrl+C stay separate),
# but safe to run directly too: `scripts/dev/run_api.sh`.
set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "vrm_api is already running on :8000 — nothing to do here."
  echo "Press any key to close this window."
  read -n 1 -s
  exit 0
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "No .venv found at repo root. First-time setup:"
  echo "  python3 -m venv .venv && source .venv/bin/activate"
  echo "  .venv/bin/python -m pip install -r requirements-api.txt"
  echo "Press any key to close this window."
  read -n 1 -s
  exit 1
fi

echo "Starting vrm_api on http://localhost:8000 ..."
# .venv/bin/python -m uvicorn (not bare `uvicorn`) — see vrm_api/README.md:
# a conda `base` environment on PATH can otherwise shadow this venv.
exec .venv/bin/python -m uvicorn vrm_api.main:app --reload
