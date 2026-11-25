"""Command line: python -m onboarding_agent load data/sample_events"""
import argparse
import logging
import sys
from pathlib import Path

from .approvals import (
    ApprovalError,
    approve,
    console_sender,
    get_approval,
    reject,
    send_approved,
)
from .db import connect, init_db
from .onboard import process_event
from .plan import PlanError, draft_plan


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


def run_approval_command(args: argparse.Namespace) -> int:
    """draft / approve / reject / send. Refusals print an error and exit 1."""
    conn = connect(args.db)
    init_db(conn)
    try:
        if args.command == "draft":
            approval_id = draft_plan(conn, args.candidate_id)
            print(f"approval {approval_id} is {get_approval(conn, approval_id)['status']}; nothing sent")
            print(get_approval(conn, approval_id)["draft"])
        elif args.command == "approve":
            approve(conn, args.id, args.by)
            print(f"approval {args.id} approved by {args.by}")
        elif args.command == "reject":
            reject(conn, args.id, args.by)
            print(f"approval {args.id} rejected by {args.by}")
        else:  # send
            send_approved(conn, args.id, console_sender)
            print(f"approval {args.id} sent")
    except (ApprovalError, PlanError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onboarding_agent")
    commands = parser.add_subparsers(dest="command", required=True)
    load = commands.add_parser("load", help="process a folder of offer-accepted events")
    load.add_argument("folder", type=Path)
    draft = commands.add_parser("draft", help="draft a first-week plan (saved as pending, not sent)")
    draft.add_argument("candidate_id")
    approve_cmd = commands.add_parser("approve", help="approve a pending draft")
    reject_cmd = commands.add_parser("reject", help="reject a pending draft")
    for cmd in (approve_cmd, reject_cmd):
        cmd.add_argument("id", type=int)
        cmd.add_argument("--by", required=True, help="who is deciding, e.g. the manager's name")
    send = commands.add_parser("send", help="send an approved draft (prints to the console for now)")
    send.add_argument("id", type=int)
    for cmd in (load, draft, approve_cmd, reject_cmd, send):
        cmd.add_argument("--db", default="onboarding.db", help="SQLite file (default: onboarding.db)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="warning: %(message)s")
    if args.command != "load":
        return run_approval_command(args)
    if not args.folder.is_dir():
        print(f"error: {args.folder} is not a folder", file=sys.stderr)
        return 2
    failed = load_folder(args.folder, args.db)
    if failed:
        print(f"{failed} event(s) failed; see runs_log", file=sys.stderr)
    return 1 if failed else 0  # nonzero exit so a script or CI notices


if __name__ == "__main__":
    sys.exit(main())
