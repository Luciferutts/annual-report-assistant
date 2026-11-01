"""Resolve read-only demo assets separately from writable report data."""

from __future__ import annotations

import os
from pathlib import Path

from openharness.config.paths import get_data_dir


def _package_dir() -> Path:
    return Path(__file__).resolve().parent


def _source_project_root() -> Path | None:
    package = _package_dir()
    # An installed wheel lives in site-packages, which is not a source checkout.
    root = package.parents[2]
    if ((root / "pyproject.toml").is_file()
            and root / "src" / "openharness" / "annual_reports" == package):
        return root
    return None


def resolve_demo_dir(project_root: Path | None = None) -> Path:
    """Find a source-checkout demo or the copy bundled in an installed wheel.

    An explicit project root takes precedence over source discovery. We never
    search the current working directory or unrelated user directories.
    Missing demo assets do not prevent the application from accepting uploads.
    """
    root = Path(project_root).expanduser().resolve() if project_root is not None else _source_project_root()
    if root is not None:
        source_demo = root / "data" / "annual_reports_demo"
        if (source_demo / "sources.json").is_file():
            return source_demo
    bundled_demo = _package_dir() / "_demo"
    if (bundled_demo / "sources.json").is_file():
        return bundled_demo
    raise ValueError("公开示例资源缺失，请重新安装完整项目，或上传自己的年报。")


def get_default_data_dir() -> Path:
    """Use an explicit report directory or OpenHarness's writable data area."""
    override = os.environ.get("ANNUAL_REPORT_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (get_data_dir() / "annual_reports").expanduser().resolve()


def validate_bind_host(host: str) -> str:
    """Allow loopback by default and an explicit container bind only."""
    if host not in ("127.0.0.1", "0.0.0.0"):
        raise ValueError("监听地址仅支持 127.0.0.1，或容器模式下显式使用 0.0.0.0。")
    return host
