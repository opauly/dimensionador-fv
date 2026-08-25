#!/bin/bash
# Runs the Next.js web app in the foreground. Called by
# start_vrm_monitor.command (each service gets its own Terminal window so
# logs/Ctrl+C stay separate), but safe to run directly too:
# `scripts/dev/run_web.sh`.
set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT/victron-monitor/web"

if lsof -nP -iTCP:3000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "The web app is already running on :3000 — nothing to do here."
  echo "Press any key to close this window."
  read -n 1 -s
  exit 0
fi

# A stale Turbopack lock (from a crashed prior run) makes `next dev` refuse
# to bind :3000 even when nothing is actually listening there anymore — the
# lsof check above is the real guard; this just clears a known false alarm.
if [ -d ".next/dev" ] && ! lsof -nP -iTCP:3000 -sTCP:LISTEN >/dev/null 2>&1; then
  rm -rf .next/dev
fi

if [ ! -f "$HOME/.nvm/nvm.sh" ]; then
  echo "nvm not found at ~/.nvm/nvm.sh — install nvm, or run 'npm run dev' yourself"
  echo "with Node >= 20.9 already active."
  echo "Press any key to close this window."
  read -n 1 -s
  exit 1
fi
source "$HOME/.nvm/nvm.sh"
nvm use

if [ ! -d node_modules ]; then
  echo "No node_modules yet — running npm install first (one-time)..."
  npm install
fi

echo "Starting the web app on http://localhost:3000 ..."
exec npm run dev
