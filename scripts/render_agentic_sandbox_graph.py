#!/usr/bin/env python3
"""Render Mermaid/markdown (and optional PNG) for the agentic sandbox LangGraph."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.agentic_sandbox.agentic_graph_visualization import (
    DEFAULT_MD_PATH,
    DEFAULT_MMD_PATH,
    DEFAULT_PNG_PATH,
    render_agentic_sandbox_graph,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render agentic sandbox LangGraph visualization (no ticket data).",
    )
    parser.add_argument(
        "--mermaid-output",
        type=Path,
        default=DEFAULT_MMD_PATH,
        help="Mermaid output path (default: reports/agentic_sandbox_graph.mmd)",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_MD_PATH,
        help="Markdown report path (default: reports/agentic_sandbox_graph.md)",
    )
    parser.add_argument(
        "--png-output",
        type=Path,
        default=DEFAULT_PNG_PATH,
        help="Optional PNG path (default: reports/agentic_sandbox_graph.png)",
    )
    parser.add_argument(
        "--no-png",
        action="store_true",
        help="Skip optional PNG rendering attempt",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )
    args = parser.parse_args(argv)

    outputs = (args.mermaid_output, args.markdown_output)
    if not args.no_png:
        outputs = (*outputs, args.png_output)
    for path in outputs:
        if path.exists() and not args.overwrite:
            print(f"render_agentic_sandbox_graph: output exists: {path} (use --overwrite)")
            return 2

    result = render_agentic_sandbox_graph(
        mermaid_output=args.mermaid_output,
        markdown_output=args.markdown_output,
        png_output=args.png_output,
        try_png=not args.no_png,
    )

    print("render_agentic_sandbox_graph: success")
    print(f"  mermaid={result.mermaid_path.resolve()}")
    print(f"  markdown={result.markdown_path.resolve()}")
    if result.png_path:
        print(f"  png={result.png_path.resolve()}")
    elif result.png_render_attempted:
        print("  png=skipped (optional renderer unavailable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
