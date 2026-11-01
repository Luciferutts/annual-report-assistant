"""Run the bundled offline suite with isolated configuration and no real keys."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="annual-report-tests-") as temporary:
        base = Path(temporary)
        environment = os.environ.copy()
        for name in list(environment):
            if (name.endswith("_API_KEY") or name.startswith("OPENHARNESS_")
                    or name in {"OPENAI_BASE_URL", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN"}):
                environment.pop(name, None)
        environment.update({
            "OPENHARNESS_CONFIG_DIR": str(base / "config"),
            "OPENHARNESS_DATA_DIR": str(base / "data"),
            "OPENHARNESS_LOGS_DIR": str(base / "logs"),
            "ANNUAL_REPORT_DATA_DIR": str(base / "reports"),
            "CLAUDE_HOME": str(base / "claude"),
            "OHMO_HOME": str(base / "ohmo"),
            "PYTHONPATH": str(root / "src"),
            "PATH": str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", ""),
        })
        return subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "-q"],
            cwd=root, env=environment, check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
