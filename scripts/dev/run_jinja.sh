#!/bin/bash
# Runs the Dimensionador Flask/Jinja2 frontend (the migration branch) in the
# foreground. This is the main_jinja counterpart to
# scripts/dev/run_dimensionador.sh on the main (Streamlit) branch/worktree —
# the two are meant to run side by side on different ports for comparison.
set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Dimensionador (Jinja2) is already running on :8000 — nothing to do here."
  exit 0
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "No .venv found at repo root. First-time setup:"
  echo "  python3.9 -m venv .venv"
  echo "  .venv/bin/python -m pip install -r requirements.txt"
  exit 1
fi

if [ ! -f ".env" ]; then
  echo "No .env found. Copy it from the main worktree (same Supabase project):"
  echo "  cp ../Claude/.env ."
  exit 1
fi

echo "Starting Dimensionador (Jinja2) on http://localhost:8000 ..."
exec .venv/bin/python run.py
