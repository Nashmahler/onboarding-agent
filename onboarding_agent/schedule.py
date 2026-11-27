"""Reschedule: recompute due dates for OPEN tasks using the current rules (weekends, holidays, templates).

Runs inside "Run onboarding". A completed task is never touched: the UPDATE itself only matches rows
whose completed_date is NULL. Each change is logged to runs_log with the old and new date, and one
Slack summary is posted per run, only when something changed."""
import sqlite3
from dataclasses import dataclass

from . import slack
from .holidays import load_holidays
from .onboard import due_date, log_run
from .templates import tasks_for


@dataclass(frozen=True)
class Change:
    candidate_id: str
    hire: str
    task: str
    owner_role: str
    old: str
    new: str


def summary_message(changes: list[Change]) -> str:
    lines = [f":calendar: *Due dates changed* for {len(changes)} open task(s) (company holidays or updated rules):"]
    lines += [
        f"- {slack.escape(c.task)} for {slack.escape(c.hire)} ({slack.escape(c.owner_role)}): {c.old} → {c.new}"
        for c in changes
    ]
    return "\n".join(lines)


def reschedule_open_tasks(conn: sqlite3.Connection, holidays: frozenset[str] | None = None) -> list[Change]:
    """Recompute every open task's due date. Return what changed (nothing posted if nothing changed)."""
    holidays = load_holidays() if holidays is None else holidays
    offsets: dict[str, dict[str, int]] = {}  # department -> {task name: offset_days}, from the templates
    changes: list[Change] = []
    rows = conn.execute(
        """SELECT t.id, t.task, t.owner_role, t.due_date, e.candidate_id, e.name, e.department, e.start_date
           FROM onboarding_tasks AS t JOIN employees AS e ON e.id = t.employee_id
           WHERE t.completed_date IS NULL ORDER BY e.id, t.due_date, t.task"""
    ).fetchall()
    for r in rows:
        by_task = offsets.setdefault(r["department"], {t.task: t.offset_days for t in tasks_for(r["department"])})
        if r["task"] not in by_task:
            continue  # no longer in the templates: leave it as it is
        new = due_date(r["start_date"], by_task[r["task"]], holidays)
        if new == r["due_date"]:
            continue
        with conn:
            cursor = conn.execute(  # "completed_date IS NULL" again: a done task can never change
                "UPDATE onboarding_tasks SET due_date = ? WHERE id = ? AND completed_date IS NULL", (new, r["id"])
            )
        if cursor.rowcount == 0:
            continue
        change = Change(r["candidate_id"], r["name"], r["task"], r["owner_role"], r["due_date"], new)
        changes.append(change)
        log_run(conn, f"reschedule {r['candidate_id']}", "ok", f"{r['task']}: {r['due_date']} → {new}")
    if changes:
        try:  # the new dates are saved; a Slack problem is logged and alerted, not fatal
            slack.post(summary_message(changes))
        except slack.SlackError as exc:
            log_run(conn, "notify reschedule", "failed", str(exc))
    return changes
