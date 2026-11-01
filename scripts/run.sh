#!/usr/bin/env bash
set -euo pipefail

REPORT_PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPORT_PROJECT_DIR"

if command -v uv >/dev/null 2>&1; then
  exec uv run --locked --extra reports annual-report-assistant --open "$@"
fi

if [[ -x "$REPORT_PROJECT_DIR/.venv/bin/python" ]]; then
  export PYTHONPATH="$REPORT_PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
  if "$REPORT_PROJECT_DIR/.venv/bin/python" -c 'import openharness.annual_reports.server' >/dev/null 2>&1; then
    exec "$REPORT_PROJECT_DIR/.venv/bin/python" -m openharness.annual_reports --open "$@"
  fi
fi

cat >&2 <<'MESSAGE'
还没有准备好当前项目的运行环境。

推荐先安装 uv，然后在项目目录执行：
  uv sync --locked --extra reports

或使用 Python 3.10+（推荐 3.12）：
  python3 -m venv .venv
  .venv/bin/python -m pip install -e '.[reports]'

完成后重新启动。详细步骤见 README.md。
MESSAGE
exit 1
