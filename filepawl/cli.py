"""Command-line entry point."""

from __future__ import annotations

import argparse


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="filepawl")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("check")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "check":
        # Phase 0 placeholder; replaced in Phase 3
        return 0

    parser.print_help()
    return 0
