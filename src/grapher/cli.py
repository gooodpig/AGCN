from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .converter import convert_ggb_to_asy
from .interactive import generate_interactive_html


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert a GeoGebra .ggb file to Asymptote code.")
    parser.add_argument("input", help="GeoGebra .ggb file")
    parser.add_argument("-o", "--output", help="Output .asy file")
    style_group = parser.add_mutually_exclusive_group()
    style_group.add_argument(
        "--preserve-style",
        action="store_true",
        help="Preserve exact GeoGebra colors (including gray) and line widths.",
    )
    style_group.add_argument(
        "--no-style",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Add parser details and unsupported-object comments to the output.",
    )
    parser.add_argument(
        "--coordinates-only",
        action="store_true",
        help="Write all points as numeric coordinates instead of symbolic constructions.",
    )
    parser.add_argument(
        "--interactive-output",
        metavar="HTML",
        help="Also create a self-contained interactive HTML preview with draggable free points.",
    )
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.with_suffix(".asy")
    try:
        result = convert_ggb_to_asy(
            input_path,
            output_path,
            preserve_style=args.preserve_style,
            debug=args.debug,
            symbolic=not args.coordinates_only,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))

    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"Wrote {output_path}")
    if args.interactive_output:
        interactive_path = Path(args.interactive_output)
        generate_interactive_html(input_path, interactive_path)
        print(f"Wrote {interactive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


