"""Draft a first-week plan for a new hire: one Claude call, saved as a pending approval.

The model only writes the friendly prose. Every date comes from the database,
and the dated checklist is appended by code, never written by the model.
"""
import os
import sqlite3
from datetime import date, timedelta

from .approvals import create_draft
from .onboard import log_run

KIND = "first_week_plan"
MODEL = "claude-haiku-5-5"
KEY_VAR = "ONBOARDING_API_KEY"  # not ANTHROPIC_API_KEY; passed to the client explicitly
WINDOW_DAYS = 14  # how far past day one the checklist reaches
SAMPLE_LABEL = f"[SAMPLE PLAN: {KEY_VAR} is not set, so Claude was not called]"


class PlanError(Exception):
    """The plan could not be drafted."""


def _make_client(api_key: str):
    import anthropic  # imported here so tests and the sample path work without it

    return anthropic.Anthropic(api_key=api_key)


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


def build_prompt(employee: sqlite3.Row, tasks: list[sqlite3.Row]) -> str:
    task_names = "\n".join(f"- {t['task']}" for t in tasks) or "- (none listed)"
    return (
        "Write a short, warm first-week plan (under 150 words) for a new hire at Juniper Labs, "
        "a fictional company. Address them by first name and sign off from their manager.\n"
        f"Name: {employee['name']}\nRole: {employee['title']}\n"
        f"Team: {employee['department']}\nLocation: {employee['location']}\n"
        f"Manager: {employee['manager_name']}\n"
        f"Things already scheduled this week:\n{task_names}\n\n"
        "Rules: do not write any dates, weekdays or numbers of days; a checklist with the "
        "real dates is added separately. Do not invent meetings, names or tools."
    )


def _ask_claude(client, employee: sqlite3.Row, tasks: list[sqlite3.Row]) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": build_prompt(employee, tasks)}],
    )
    text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
    if not text:
        raise PlanError("Claude returned no text")
    return text


def draft_plan(conn: sqlite3.Connection, candidate_id: str, client=None) -> int:
    """Draft and save a pending first-week plan. Return the approval id.

    `client` is for tests (a fake). Without it, the real client is built from
    ONBOARDING_API_KEY; if that is not set, a labeled sample plan is used instead.
    """
    step = f"draft {candidate_id}"
    employee = conn.execute(
        "SELECT * FROM employees WHERE candidate_id = ?", (candidate_id,)
    ).fetchone()
    if employee is None:
        log_run(conn, step, "failed", f"unknown candidate {candidate_id}")
        raise PlanError(f"unknown candidate {candidate_id}")

    # One plan per hire. This check comes BEFORE the Claude call, so re-running
    # `draft` can never spend a second call (the cap is 3 per hire).
    existing = conn.execute(
        "SELECT id FROM approvals WHERE employee_id = ? AND kind = ?", (employee["id"], KIND)
    ).fetchone()
    if existing:
        log_run(conn, step, "skipped", f"approval {existing['id']} already exists")
        return existing["id"]

    tasks = first_week_tasks(conn, employee)
    checklist = build_checklist(tasks)
    api_key = os.environ.get(KEY_VAR)

    if client is None and not api_key:
        draft = f"{SAMPLE_LABEL}\n\nHi {employee['name'].split()[0]}, welcome to the team!\n\n{checklist}"
        approval_id = create_draft(conn, employee["id"], KIND, draft)
        log_run(conn, step, "skipped", f"no {KEY_VAR}; sample plan saved as pending approval {approval_id}")
        return approval_id

    try:
        prose = _ask_claude(client or _make_client(api_key), employee, tasks)
    except Exception as exc:  # network, auth, empty reply: log it, save nothing
        log_run(conn, step, "failed", f"Claude call failed: {exc}")
        raise PlanError(f"Claude call failed: {exc}") from exc

    approval_id = create_draft(conn, employee["id"], KIND, f"{prose}\n\n{checklist}")
    log_run(conn, step, "ok", f"draft saved as pending approval {approval_id}")
    return approval_id
