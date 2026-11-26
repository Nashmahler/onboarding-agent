"""Overdue report: open tasks past their due date, grouped by owner.

The counting and the date comparison are done by SQL (queries/*.sql). "Today" is
decided here, in Python, and handed to SQL as a parameter, so the same date logic
can be tested with a fixed day and the model never touches a date.
"""
import sqlite3
from datetime import date
from pathlib import Path

from . import slack
from .onboard import log_run

QUERIES = Path(__file__).resolve().parent.parent / "queries"


def _query(conn: sqlite3.Connection, name: str, today: str) -> list[sqlite3.Row]:
    return conn.execute((QUERIES / name).read_text(), {"today": today}).fetchall()


def build_report(conn: sqlite3.Connection, today: str) -> str:
    """Return the report text for the given day (YYYY-MM-DD)."""
    owners = _query(conn, "overdue_by_owner.sql", today)
    if not owners:
        return f"Overdue report for {today}: nothing is overdue."
    total = sum(r["overdue_tasks"] for r in owners)
    lines = [f"Overdue report for {today}: {total} open task(s) past due", ""]
    tasks = _query(conn, "overdue_tasks.sql", today)
    for owner in owners:
        lines.append(f"{owner['owner_role']}: {owner['overdue_tasks']} overdue (oldest {owner['days_late']} days late)")
        lines += [
            f"  - {t['task']} for {t['new_hire']}, due {t['due_date']} ({t['days_late']}d late)"
            for t in tasks if t["owner_role"] == owner["owner_role"]
        ]
    return "\n".join(lines)


def run_report(conn: sqlite3.Connection, post: bool, today: str | None = None) -> str:
    """Build the report, print it, and optionally post it to Slack. Always logged."""
    today = today or date.today().isoformat()
    report = build_report(conn, today)
    print(report)
    if post:
        try:
            head, *rest = report.splitlines()
            body = "\n".join(rest).strip()
            slack.post(f"*{slack.escape(head)}*" + (f"\n```{slack.escape(body)}```" if body else ""))
        except slack.SlackError as exc:
            log_run(conn, "overdue report", "failed", str(exc))
            raise
    log_run(conn, "overdue report", "ok", report.splitlines()[0])
    return report
