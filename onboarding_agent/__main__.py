"""Command line: python -m onboarding_agent load data/sample_events"""
import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from . import dashboard, metrics, overdue, schedule, slack
from .approvals import (
    ApprovalError,
    approve,
    get_approval,
    reject,
    send_approved,
)
from .db import connect, init_db
from .onboard import log_run, process_event
from .plan import PlanError, draft_plan
from .tasks import TaskError, complete_task


def _process_folder(conn, folder: Path) -> list:
    """Process every *.json event in a folder, in name order. Return the Results."""
    results = []
    for path in sorted(folder.glob("*.json")):
        result = process_event(conn, path)
        print(f"{result.status:>7}  {path.name}: {result.detail}")
        results.append(result)
    return results


def load_folder(folder: Path, db_path: str) -> int:
    """Process every event in a folder. Return how many failed."""
    conn = connect(db_path)
    init_db(conn)
    return sum(r.status == "failed" for r in _process_folder(conn, folder))


def run_onboarding(folder: Path, db_path: str) -> int:
    """The "Run onboarding" button: load every event, then draft a plan for each hire.

    Exit 0 when every failure was written to runs_log AND alerted (cand_1005 is a planted
    failure, so this is the normal result). Exit 1 only for something unexpected: a crash,
    or an alert that could not be delivered (recorded as a 'slack alert' failed row)."""
    conn = connect(db_path)
    init_db(conn)
    last_row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM runs_log").fetchone()[0]
    try:
        results = _process_folder(conn, folder)
        moved = schedule.reschedule_open_tasks(conn)  # open tasks only; each change logged, one Slack summary
        print(f"rescheduled {len(moved)} open task(s)")
        for result in results:
            if result.employee_id is None:
                continue  # that event failed; its failure is already logged and alerted
            candidate_id = conn.execute(
                "SELECT candidate_id FROM employees WHERE id = ?", (result.employee_id,)
            ).fetchone()[0]
            try:
                approval_id = draft_plan(conn, candidate_id)
                print(f"{candidate_id}: approval {approval_id} is {get_approval(conn, approval_id)['status']}")
            except PlanError as exc:  # already logged and alerted by draft_plan
                print(f"{candidate_id}: {exc}", file=sys.stderr)
    except Exception as exc:  # unexpected: log it (which alerts), then fail the run
        log_run(conn, "run onboarding", "failed", f"unexpected error: {type(exc).__name__}: {exc}")
        return 1
    handled = conn.execute(
        "SELECT COUNT(*) FROM runs_log WHERE id > ? AND status = 'failed' AND step != ?",
        (last_row, slack.ALERT_FAILED_STEP),
    ).fetchone()[0]
    undelivered = conn.execute(
        "SELECT COUNT(*) FROM runs_log WHERE id > ? AND step = ?", (last_row, slack.ALERT_FAILED_STEP)
    ).fetchone()[0]
    print(f"{handled} step(s) failed and were logged and alerted; {undelivered} alert(s) not delivered")
    return 1 if undelivered else 0


def run_approval_command(args: argparse.Namespace) -> int:
    """draft / approve / reject / send / overdue. Refusals print an error and exit 1."""
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
            if args.send:  # still goes through send_approved, which re-checks the status
                send_approved(conn, args.id, slack.slack_sender)
                print(f"approval {args.id} sent")
        elif args.command == "reject":
            reject(conn, args.id, args.by, args.reason)
            print(f"approval {args.id} rejected by {args.by}")
        else:  # send
            send_approved(conn, args.id, slack.slack_sender)
            print(f"approval {args.id} sent")
    except (ApprovalError, PlanError, slack.SlackError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def run_overdue_command(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    init_db(conn)
    try:
        overdue.run_report(conn, post=args.post, today=args.today)
    except slack.SlackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def run_complete_command(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    init_db(conn)
    try:
        day = complete_task(conn, args.candidate_id, args.task, args.by)
    except TaskError as exc:  # already logged (and alerted) by complete_task
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{args.task!r} for {args.candidate_id} completed on {day} by {args.by}")
    return 0


def run_metrics_command(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    init_db(conn)
    print(metrics.build_metrics(conn, args.today or date.today().isoformat()))
    return 0


def run_dashboard_command(args: argparse.Namespace) -> int:
    """Read-only: builds the page from the database. A failure is logged (and alerted)."""
    conn = connect(args.db)
    init_db(conn)
    try:
        path = dashboard.write_dashboard(conn, args.out, args.today)
    except Exception as exc:
        log_run(conn, "dashboard", "failed", f"{type(exc).__name__}: {exc}")
        return 1
    print(f"wrote {path}")
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
    reject_cmd.add_argument("--reason", required=True, help="why it is rejected (saved and posted to Slack)")
    approve_cmd.add_argument("--send", action="store_true", help="also send it to Slack right after approving")
    send = commands.add_parser("send", help="send an approved draft to Slack (or the console if no webhook)")
    send.add_argument("id", type=int)
    run = commands.add_parser("run", help="load events, then draft a plan for each hire (the Run onboarding button)")
    run.add_argument("folder", type=Path)
    report = commands.add_parser("overdue", help="report open tasks past their due date, grouped by owner")
    report.add_argument("--post", action="store_true", help="also post the report to Slack")
    report.add_argument("--today", help="pretend today is this YYYY-MM-DD (for demos and tests)")
    complete = commands.add_parser("complete", help="mark one onboarding task done (date is set by the code)")
    complete.add_argument("candidate_id")
    complete.add_argument("--task", required=True, help="the exact task name, e.g. 'Add to payroll'")
    complete.add_argument("--by", required=True, help="who finished it (logged and posted to Slack)")
    metrics_cmd = commands.add_parser("metrics", help="print days-to-day-one-done and overdue tasks by owner")
    metrics_cmd.add_argument("--today", help="pretend today is this YYYY-MM-DD")
    page = commands.add_parser("dashboard", help="write the static dashboard page from the database")
    page.add_argument("--out", default="docs/index.html", help="where to write it (default: docs/index.html)")
    page.add_argument("--today", help="pretend today is this YYYY-MM-DD")
    for cmd in (load, draft, approve_cmd, reject_cmd, send, run, report, complete, metrics_cmd, page):
        cmd.add_argument("--db", default="onboarding.db", help="SQLite file (default: onboarding.db)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="warning: %(message)s")
    if args.command == "overdue":
        return run_overdue_command(args)
    if args.command == "complete":
        return run_complete_command(args)
    if args.command == "metrics":
        return run_metrics_command(args)
    if args.command == "dashboard":
        return run_dashboard_command(args)
    if args.command not in ("load", "run"):
        return run_approval_command(args)
    if not args.folder.is_dir():
        print(f"error: {args.folder} is not a folder", file=sys.stderr)
        return 2
    if args.command == "run":
        return run_onboarding(args.folder, args.db)
    failed = load_folder(args.folder, args.db)
    if failed:
        print(f"{failed} event(s) failed; see runs_log", file=sys.stderr)
    return 1 if failed else 0  # nonzero exit so a script or CI notices


if __name__ == "__main__":
    sys.exit(main())
