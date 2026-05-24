#!/usr/bin/env python3
"""Launch the internal Streamlit operator console (local only)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_APP_PATH = Path(__file__).resolve().parents[1] / "app/operator_console/streamlit_app.py"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run internal operator console (Streamlit). "
            "Aggregate AI assist + retrieval summaries only; not customer-facing."
        ),
    )
    parser.add_argument(
        "--server-port",
        type=int,
        default=8501,
        help="Streamlit server port (default: 8501)",
    )
    args = parser.parse_args(argv)

    try:
        import streamlit  # noqa: F401
    except ImportError:
        print(
            "run_operator_console: streamlit is not installed. "
            'Install with: pip install -e ".[operator]"',
            file=sys.stderr,
        )
        return 1

    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(_APP_PATH),
        "--server.port",
        str(args.server_port),
        "--",
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
