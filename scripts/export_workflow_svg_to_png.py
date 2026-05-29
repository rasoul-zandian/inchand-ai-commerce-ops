"""Optional local helper to export the workflow SVG to PNG.

Usage:
  PYTHONPATH=. python3.11 scripts/export_workflow_svg_to_png.py
  PYTHONPATH=. python3.11 scripts/export_workflow_svg_to_png.py --scale 2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_SVG = Path("docs/architecture/agentic_graph_read_only_tools_workflow.svg")
DEFAULT_PNG = Path("docs/architecture/agentic_graph_read_only_tools_workflow.png")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export workflow SVG to PNG (optional helper).")
    parser.add_argument("--svg", type=Path, default=DEFAULT_SVG, help="Input SVG path.")
    parser.add_argument("--png", type=Path, default=DEFAULT_PNG, help="Output PNG path.")
    parser.add_argument("--scale", type=float, default=1.0, help="Output scale (default: 1.0).")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.svg.is_file():
        print(f"SVG not found: {args.svg}", file=sys.stderr)
        return 1
    if args.scale <= 0:
        print("--scale must be > 0", file=sys.stderr)
        return 1

    try:
        import cairosvg
    except Exception as exc:  # noqa: BLE001
        print(
            "cairosvg is required for PNG export. Install with: pip install cairosvg",
            file=sys.stderr,
        )
        print(f"Import error: {exc}", file=sys.stderr)
        return 2

    args.png.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(url=str(args.svg), write_to=str(args.png), scale=args.scale)
    print(f"Exported PNG: {args.png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
