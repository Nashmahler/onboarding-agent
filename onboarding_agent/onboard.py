"""Turn one "offer accepted" event into an employee row plus their task rows."""
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .events import EventError, NewHire, parse_event
from .templates import TemplateError, has_department, tasks_for


@dataclass(frozen=True)
class Result:
    status: str  # 'ok', 'skipped' or 'failed'
    detail: str
    employee_id: int | None = None
    tasks_created: int = 0


def due_date(start_date: str, offset_days: int) -> str:
    """Start date + offset, kept off weekends (Monday is 0, Saturday 5, Sunday 6).
    Before day one (negative offset): back to the previous Friday, so it still
    happens before the hire starts. Otherwise: forward to the next Monday."""
    day = date.fromisoformat(start_date) + timedelta(days=offset_days)
    if day.weekday() >= 5:
        if offset_days < 0:
            day -= timedelta(days=day.weekday() - 4)  # Saturday -1, Sunday -2
        else:
            day += timedelta(days=7 - day.weekday())  # Saturday +2, Sunday +1
    return day.isoformat()


def add_employee(conn: sqlite3.Connection, hire: NewHire) -> int:
    """Insert the employee (skipped if they exist) and return their id."""
    conn.execute(
        """INSERT INTO employees (candidate_id, name, email, title, department, manager_name,
                                  manager_email, location, offer_accepted_date, start_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(candidate_id) DO NOTHING""",
        (hire.candidate_id, hire.name, hire.email, hire.title, hire.department,
         hire.manager_name, hire.manager_email, hire.location,
         hire.offer_accepted_date, hire.start_date),
    )
    row = conn.execute(
        "SELECT id FROM employees WHERE candidate_id = ?", (hire.candidate_id,)
    ).fetchone()
    return row["id"]


def create_tasks(conn: sqlite3.Connection, employee_id: int, hire: NewHire) -> int:
    """Insert each template task (existing ones are skipped). Return how many were new."""
    created = 0
    for t in tasks_for(hire.department):
        cursor = conn.execute(
            """INSERT INTO onboarding_tasks (employee_id, task, owner_role, due_date)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(employee_id, task) DO NOTHING""",
            (employee_id, t.task, t.owner_role, due_date(hire.start_date, t.offset_days)),
        )
        created += cursor.rowcount  # 1 if inserted, 0 if it already existed
    return created


def log_run(conn: sqlite3.Connection, step: str, status: str, detail: str) -> None:
    """Write one row to runs_log. ran_at is set here in code, in UTC."""
    ran_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conn:
        conn.execute(
            "INSERT INTO runs_log (ran_at, step, status, detail) VALUES (?, ?, ?, ?)",
            (ran_at, step, status, detail),
        )


def _describe(hire: NewHire, created: int) -> str:
    detail = f"{hire.name}: {created} tasks created"
    if not has_department(hire.department):
        detail += f" (no department tasks for {hire.department!r})"
    return detail


def process_event(conn: sqlite3.Connection, path: str | Path) -> Result:
    """Run one event end to end, log it, and never let a bad event stop the batch."""
    step = f"onboard {Path(path).name}"
    try:
        hire = parse_event(path)
        with conn:  # one transaction: all of it is saved, or none of it
            employee_id = add_employee(conn, hire)
            created = create_tasks(conn, employee_id, hire)
    except (EventError, TemplateError, sqlite3.Error) as exc:
        log_run(conn, step, "failed", str(exc))
        return Result("failed", str(exc))
    status = "ok" if created else "skipped"
    detail = _describe(hire, created)
    log_run(conn, step, status, detail)
    return Result(status, detail, employee_id, created)
