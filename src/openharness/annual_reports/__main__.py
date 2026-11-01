"""Run with python -m openharness.annual_reports."""

import argparse
from pathlib import Path

from .server import serve


def main() -> None:
    parser = argparse.ArgumentParser(description="本地年报分析助手")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--host", choices=("127.0.0.1", "0.0.0.0"), default="127.0.0.1",
                        help="默认仅本机访问；容器运行时可显式指定 0.0.0.0。")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--open", action="store_true", dest="open_browser")
    arguments = parser.parse_args()
    serve(arguments.port, arguments.data_dir, arguments.open_browser, host=arguments.host)


if __name__ == "__main__":
    main()
