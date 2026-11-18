#!/usr/bin/env bash
# setup.sh - first-time setup: makes FOLM's own Python environment (.venv) and checks system tools.
# Run it once after downloading FOLM, then start the app with ./run-folm.sh
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    echo "Making FOLM's Python environment in .venv ..."
    if command -v uv >/dev/null; then
        uv venv .venv
        uv pip install --python .venv/bin/python -r requirements.txt
    else
        if ! python3 -m venv .venv 2>/dev/null; then
            rm -rf .venv
            echo "Python's venv module is missing. Install it (Debian/Ubuntu/Mint: sudo apt install python3-venv)"
            echo "or install uv (https://docs.astral.sh/uv/), then run ./setup.sh again."
            exit 1
        fi
        .venv/bin/python -m pip install --quiet --upgrade pip
        .venv/bin/python -m pip install --quiet -r requirements.txt
    fi
else
    echo "Python environment already set up (.venv)."
fi

echo
.venv/bin/python folm.py doctor || true
echo
echo "Done. Start FOLM with:  ./run-folm.sh"
echo "Optional: ./make-shortcut.sh adds FOLM to your app menu and lets Nexus 'Mod Manager Download' buttons open it."
