#!/bin/zsh
REPORT_PROJECT_DIR="${0:A:h}"
exec /bin/bash "$REPORT_PROJECT_DIR/scripts/run.sh" "$@"
