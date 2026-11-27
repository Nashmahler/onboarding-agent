"""The approval gate. Every draft starts 'pending'; only a person moves it forward.

This module is the ONLY place that changes approvals.status. The one way to send
is send_approved(), which flips approved -> sent in a single SQL statement and
only then runs the sender. A draft that is not approved raises before any
sending code is reached.
"""
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone

from . import slack
from .checklist import refresh_draft
from .onboard import log_run


class ApprovalError(Exception):
    """An approval step was refused (wrong status, unknown id, missing name)."""


class NotApprovedError(ApprovalError):
    """Someone tried to send a draft that is not approved."""


# A sender takes (the approval as a dict-like row, the employee row) and delivers the draft.
Sender = Callable[[sqlite3.Row, sqlite3.Row], None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_draft(conn: sqlite3.Connection, employee_id: int, kind: str, draft: str) -> int:
    """Save a new draft. There is no status argument on purpose: it is always 'pending'."""
    with conn:
        cursor = conn.execute(
            "INSERT INTO approvals (employee_id, kind, draft) VALUES (?, ?, ?)",
            (employee_id, kind, draft),
        )
    return cursor.lastrowid


def get_approval(conn: sqlite3.Connection, approval_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
    if row is None:
        raise ApprovalError(f"no approval with id {approval_id}")
    return row


def _decide(conn: sqlite3.Connection, approval_id: int, new_status: str, by: str, reason: str | None = None) -> None:
    by = (by or "").strip()
    if not by:
        raise ApprovalError("a name is required to approve or reject (use --by)")
    step = f"{new_status} approval {approval_id}"
    with conn:
        # Only a pending draft can be decided. The status check is part of the UPDATE,
        # so a rejected or sent draft can never be flipped back to approved.
        cursor = conn.execute(
            """UPDATE approvals SET status = ?, decided_by = ?, decided_at = ?, reason = ?
               WHERE id = ? AND status = 'pending'""",
            (new_status, by, _now(), reason, approval_id),
        )
    if cursor.rowcount == 0:
        current = get_approval(conn, approval_id)["status"]  # raises if the id is unknown
        message = f"approval {approval_id} is {current}, only a pending draft can be {new_status}"
        log_run(conn, step, "failed", message)
        raise ApprovalError(message)
    log_run(conn, step, "ok", f"{new_status} by {by}")


def approve(conn: sqlite3.Connection, approval_id: int, by: str) -> None:
    _decide(conn, approval_id, "approved", by)


def reject(conn: sqlite3.Connection, approval_id: int, by: str, reason: str) -> None:
    """Reject a pending draft. A reason is required: the next drafter and the team can see why."""
    reason = (reason or "").strip()
    if not reason:
        raise ApprovalError("a reason is required to reject (use --reason)")
    _decide(conn, approval_id, "rejected", by, reason)
    try:  # the rejection already stands; a Slack problem is logged and alerted, not fatal
        slack.post(slack.rejected_message(approval_id, by.strip(), reason))
    except slack.SlackError as exc:
        log_run(conn, f"notify rejection {approval_id}", "failed", str(exc))


def send_approved(conn: sqlite3.Connection, approval_id: int, sender: Sender) -> None:
    """Send a draft, but only if a person approved it. This is the only way to send."""
    step = f"send approval {approval_id}"
    with conn:
        # Check and change in ONE statement: it only matches an approved draft, and it
        # moves it to 'sent' at once, so the same draft cannot be sent twice.
        cursor = conn.execute(
            "UPDATE approvals SET status = 'sent' WHERE id = ? AND status = 'approved'",
            (approval_id,),
        )
    if cursor.rowcount == 0:
        current = get_approval(conn, approval_id)["status"]  # raises if the id is unknown
        message = f"approval {approval_id} is {current}, not approved: nothing was sent"
        log_run(conn, step, "failed", message)
        raise NotApprovedError(message)

    # Only now, with the row already marked sent, does any delivery code run.
    row = get_approval(conn, approval_id)
    employee = conn.execute("SELECT * FROM employees WHERE id = ?", (row["employee_id"],)).fetchone()
    refreshed = False
    try:
        # The checklist is rebuilt from the database NOW, so an approved plan shows current dates.
        # The approved prose is kept word for word, and the stored draft is not edited.
        fresh = refresh_draft(conn, row["draft"], employee)
        refreshed = fresh != row["draft"]
        sender(dict(row) | {"draft": fresh}, employee)
    except Exception as exc:
        with conn:  # delivery failed: put it back so a person can retry
            conn.execute(
                "UPDATE approvals SET status = 'approved' WHERE id = ? AND status = 'sent'",
                (approval_id,),
            )
        log_run(conn, step, "failed", f"delivery failed, still approved: {exc}")
        raise
    note = "; checklist dates refreshed from the database" if refreshed else ""
    log_run(conn, step, "ok", f"sent to {employee['name']} and {employee['manager_name']}{note}")


def console_sender(approval: sqlite3.Row, employee: sqlite3.Row) -> None:
    """Stand-in delivery until Session 3 adds Slack: print the message."""
    print(f"To: {employee['name']} <{employee['email']}>, cc {employee['manager_email']}")
    print(approval["draft"])
