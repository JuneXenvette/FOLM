#!/bin/sh
# Start the FOLM app (uses the project's own Python environment in .venv).
cd "$(dirname "$0")" && exec .venv/bin/python folm_gui.py "$@"
