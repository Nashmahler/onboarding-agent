"""The dated checklist at the bottom of a plan. Built by code from the database, never by the model.

A draft is stored as "prose + checklist". When the plan is SENT, the checklist is rebuilt from the
database (refresh_draft), so an approved plan always shows current due dates. The stored,
approved text is never edited."""
import sqlite3
from datetime import date, timedelta

WINDOW_DAYS = 14  # how far past day one the checklist reaches
HEADERS = ("Your checklist for the first two weeks:", "Your checklist: no dated tasks")


def first_week_tasks(conn: sqlite3.Connection, employee: sqlite3.Row) -> list[sqlite3.Row]:
    """Tasks due from day one through the first two weeks. Dates are computed here, in code.

    Two weeks, not one: the template's own tasks (security training, benefits) fall
    in week two, and everything before day one is set up before the hire arrives."""
    start = date.fromisoformat(employee["start_date"])
    return conn.execute(
        """SELECT task, owner_role, due_date FROM onboarding_tasks
           WHERE employee_id = ? AND due_date BETWEEN ? AND ?
           ORDER BY due_date, task""",
        (employee["id"], start.isoformat(), (start + timedelta(days=WINDOW_DAYS - 1)).isoformat()),
    ).fetchall()


def build_checklist(tasks: list[sqlite3.Row]) -> str:
    if not tasks:
        return "Your checklist: no dated tasks fall in your first two weeks."
    lines = ["Your checklist for the first two weeks:"]
    lines += [f"- {t['due_date']}: {t['task']} ({t['owner_role']})" for t in tasks]
    return "\n".join(lines)


def _checklist_start(draft: str) -> int | None:
    """Index where the (last) checklist header line begins, or None if the draft has none."""
    starts = []
    for header in HEADERS:
        if draft.startswith(header):
            starts.append(0)
        found = draft.rfind("\n" + header)
        if found != -1:
            starts.append(found + 1)
    return max(starts) if starts else None


def refresh_draft(conn: sqlite3.Connection, draft: str, employee: sqlite3.Row) -> str:
    """Return the draft with its checklist rebuilt from the database right now.

    Everything before the checklist header (the approved prose) is kept word for word.
    A draft with no checklist header is returned unchanged."""
    start = _checklist_start(draft)
    if start is None:
        return draft
    prose = draft[:start].rstrip()
    checklist = build_checklist(first_week_tasks(conn, employee))
    return f"{prose}\n\n{checklist}" if prose else checklist
