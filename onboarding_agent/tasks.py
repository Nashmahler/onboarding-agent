"""Mark an onboarding task done. The date is set here, in code, never by the model or the caller."""
import sqlite3
from datetime import date

from . import slack
from .onboard import log_run


class TaskError(Exception):
    """A task could not be completed (unknown hire or task, already done, missing name)."""


def complete_task(conn: sqlite3.Connection, candidate_id: str, task: str, by: str, today: str | None = None) -> str:
    """Set completed_date for one task and log it. Return the date used.

    `today` exists only so tests can pin the day; the real date comes from the system clock."""
    by, task = (by or "").strip(), (task or "").strip()
    step = f"complete {candidate_id}"
    if not by:
        raise TaskError("a name is required (use --by)")
    employee = conn.execute("SELECT id, name FROM employees WHERE candidate_id = ?", (candidate_id,)).fetchone()
    if employee is None:
        return _refuse(conn, step, f"no hire with candidate id {candidate_id!r}")
    row = conn.execute(
        "SELECT id, task, owner_role, completed_date FROM onboarding_tasks WHERE employee_id = ? AND task = ?",
        (employee["id"], task),
    ).fetchone()
    if row is None:
        names = [r[0] for r in conn.execute("SELECT task FROM onboarding_tasks WHERE employee_id = ? ORDER BY due_date, task", (employee["id"],))]
        return _refuse(conn, step, f"{employee['name']} has no task {task!r}; tasks: {'; '.join(names)}")
    day = today or date.today().isoformat()
    with conn:
        # The "completed_date IS NULL" check is part of the UPDATE: a done task keeps its first date.
        cursor = conn.execute(
            "UPDATE onboarding_tasks SET completed_date = ? WHERE id = ? AND completed_date IS NULL", (day, row["id"])
        )
    if cursor.rowcount == 0:
        return _refuse(conn, step, f"{task!r} for {employee['name']} was already completed on {row['completed_date']}")
    log_run(conn, step, "ok", f"{task!r} for {employee['name']} completed on {day} by {by}")
    try:  # the task is saved; a Slack problem is logged and alerted, not fatal
        slack.post(f":white_check_mark: *{slack.escape(task)}* done for {slack.escape(employee['name'])} "
                   f"({slack.escape(row['owner_role'])}), marked by {slack.escape(by)} on {day}")
    except slack.SlackError as exc:
        log_run(conn, f"notify completion {candidate_id}", "failed", str(exc))
    return day


def _refuse(conn: sqlite3.Connection, step: str, message: str):
    log_run(conn, step, "failed", message)
    raise TaskError(message)
