"""Command line: python -m onboarding_agent load data/sample_events"""
import argparse
import logging
import sys
from pathlib import Path

from .db import connect, init_db
from .onboard import process_event


def load_folder(folder: Path, db_path: str) -> int:
    """Process every *.json event in a folder, in name order. Return how many failed."""
    conn = connect(db_path)
    init_db(conn)
    failed = 0
    for path in sorted(folder.glob("*.json")):
        result = process_event(conn, path)
        print(f"{result.status:>7}  {path.name}: {result.detail}")
        failed += result.status == "failed"
    return failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onboarding_agent")
    commands = parser.add_subparsers(dest="command", required=True)
    load = commands.add_parser("load", help="process a folder of offer-accepted events")
    load.add_argument("folder", type=Path)
    load.add_argument("--db", default="onboarding.db", help="SQLite file (default: onboarding.db)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="warning: %(message)s")
    if not args.folder.is_dir():
        print(f"error: {args.folder} is not a folder", file=sys.stderr)
        return 2
    failed = load_folder(args.folder, args.db)
    if failed:
        print(f"{failed} event(s) failed; see runs_log", file=sys.stderr)
    return 1 if failed else 0  # nonzero exit so a script or CI notices


if __name__ == "__main__":
    sys.exit(main())
