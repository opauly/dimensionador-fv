#!/bin/bash
# Canonical copy of the vrm_api (FastAPI pipeline service) dev-server launch
# script. Same /tmp indirection constraint documented in
# start_dimensionador.sh applies here — .claude/launch.json points at
# /tmp/start_vrm_api.sh (a copy of this file, absolute cd), not this one.
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# --reload + scoped --reload-dir (2026-08-19): a plain uvicorn process never
# picks up an edited .py file — confirmed causing real dev-mode staleness
# today (a stale vrm_api served pre-fix report-generation code for hours).
# --reload-dir is scoped to what vrm_api actually imports from (itself,
# victron/, database/) rather than the whole repo root, so editing e.g.
# victron-monitor/web/ or .venv/ never triggers a restart.
exec .venv/bin/python3 -m uvicorn vrm_api.main:app --host 0.0.0.0 --port 8000 \
  --reload --reload-dir vrm_api --reload-dir victron --reload-dir database
