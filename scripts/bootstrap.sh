#!/usr/bin/env sh
# One-time setup on macOS/Linux. Run from the nodal-accord folder:  sh scripts/bootstrap.sh
set -e
cd "$(dirname "$0")/.."
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
npm install
echo "Done. Start everything with:  npm run dev   (API :8000, worker, web :5173)"
