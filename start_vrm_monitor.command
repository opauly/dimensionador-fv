#!/bin/bash
# start_vrm_monitor.command
#
# Double-click in Finder, or run `./start_vrm_monitor.command` from
# Terminal: opens the VRM Monitor API (FastAPI, :8000) and web app
# (Next.js, :3000), each in its own Terminal window so their logs and
# Ctrl+C stay independent, then opens the landing page in your browser
# once it's ready.
#
# Safe to run again while both are already up — scripts/dev/run_api.sh and
# run_web.sh each detect their own port already listening and exit without
# starting a duplicate.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_SCRIPT="$REPO_ROOT/scripts/dev/run_api.sh"
WEB_SCRIPT="$REPO_ROOT/scripts/dev/run_web.sh"

osascript <<EOF
tell application "Terminal"
    activate
    do script "\"$API_SCRIPT\""
    delay 1
    do script "\"$WEB_SCRIPT\""
end tell
EOF

echo "Waiting for the web app to come up..."
for i in $(seq 1 60); do
  if curl -s -o /dev/null "http://localhost:3000"; then
    echo "Up — opening http://localhost:3000"
    open "http://localhost:3000"
    exit 0
  fi
  sleep 1
done
echo "Still not up after 60s — check the two Terminal windows that just opened for errors."
