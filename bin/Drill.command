#!/bin/bash
# Double-clickable launcher for the Spanish drill.
# Finder runs this from an arbitrary cwd, so resolve the repo from $0.
cd "$(dirname "$0")/.." || exit 1
PY="$(command -v python3)"
[ -x "$PY" ] || { echo "python3 not found"; read -r; exit 1; }
exec "$PY" -m drill gui "$@"
