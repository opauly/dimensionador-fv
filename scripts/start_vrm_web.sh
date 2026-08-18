#!/bin/bash
# Canonical copy of the VRM Monitor Next.js dev-server launch script.
#
# Same constraint documented in start_dimensionador.sh applies here: the
# sandboxed dev-server launcher cannot exec a script living under ~/Desktop,
# so .claude/launch.json points at /tmp/start_vrm_web.sh (a copy of this
# file, with an absolute cd instead of the BASH_SOURCE trick) rather than
# this one directly. If /tmp/start_vrm_web.sh is ever missing, recreate it
# from this file's content with the cd line made absolute.
#
# Uses the nvm-managed Node 20.20.0 explicitly (via PATH), not this
# machine's default (Node 18.20.8) — Next.js 16 requires Node >=20.9.0.
# victron-monitor/web/.nvmrc records the same version; this script just
# doesn't rely on an interactive shell having already `nvm use`'d it.
cd "$(dirname "${BASH_SOURCE[0]}")/../victron-monitor/web"
export PATH="$HOME/.nvm/versions/node/v20.20.0/bin:$PATH"
exec npm run dev
