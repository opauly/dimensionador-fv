#!/bin/bash
# Canonical copy of the vrm_api (FastAPI pipeline service) dev-server launch
# script. Same /tmp indirection constraint documented in
# start_dimensionador.sh applies here — .claude/launch.json points at
# /tmp/start_vrm_api.sh (a copy of this file, absolute cd), not this one.
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec .venv/bin/python3 -m uvicorn vrm_api.main:app --host 0.0.0.0 --port 8000
