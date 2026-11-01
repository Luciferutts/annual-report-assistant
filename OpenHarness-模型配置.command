#!/bin/zsh
PROJECT_DIR="${0:A:h}"
cd "$PROJECT_DIR" || exit 1
export PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PROJECT_DIR/.venv/bin/python" scripts/setup_window.py
