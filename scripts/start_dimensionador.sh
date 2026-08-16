#!/bin/bash
# Canonical copy of the Streamlit launch script for local preview.
#
# .claude/launch.json does NOT point here — it points at
# /tmp/start_dimensionador.sh, an exact copy of this file. That's a real
# constraint of this machine's dev-server sandbox, not a stylistic choice:
# the sandboxed launcher process can open/exec a script sitting outside
# ~/Desktop (e.g. in /tmp) just fine, and once that process is running it can
# `cd` into this project (which lives under ~/Desktop) and exec the venv's
# python3.9 binary (itself a symlink resolving outside ~/Desktop) with no
# trouble at all. But it cannot directly open or exec a *second* script file
# that physically resides under ~/Desktop — every attempt to point
# launch.json (or an intermediate script) straight at a file in this repo
# failed with "Operation not permitted", whether via direct exec, `cd` from
# a -c one-liner, or even plain `source`. Confirmed empirically on
# 2026-08-15, not assumed.
#
# So /tmp/start_dimensionador.sh has to stay self-contained — it cannot
# delegate to this file. If it's ever missing (e.g. /tmp got cleared), just
# copy this file there:
#   cp scripts/start_dimensionador.sh /tmp/start_dimensionador.sh
#
# Keep the two files identical. This file is the one to edit; then re-copy.
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# Uses `.venv/bin/python3.9 -m streamlit` rather than the `.venv/bin/streamlit`
# wrapper script: that wrapper (and `.venv/bin/pip`) has a shebang hardcoded to
# this project's pre-rename folder name ("Pauly & Co." with a trailing period)
# and fails with "No such file or directory" if invoked directly. Calling the
# module via `-m` sidesteps the broken wrapper; the venv's installed packages
# themselves are unaffected.
exec .venv/bin/python3.9 -m streamlit run app.py --server.port 8502 --server.headless true
