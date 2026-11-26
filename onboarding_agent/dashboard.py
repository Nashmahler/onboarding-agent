"""Build docs/index.html: one static page from the demo database.

Rules for this file:
- It only READS the database. It never imports the Claude client or `requests`, so it cannot
  call any API. (A test checks that.)
- It never selects an email column, and every piece of text is run through scrub() as a
  second layer: anything that looks like an email, a link or a long secret-looking string is hidden.
- No JavaScript, no external fonts or files: one page, inline CSS.
"""
import re
import sqlite3
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from . import metrics

RUN_ROWS = 20
_HIDE = [  # (pattern, replacement), applied in this order
    (re.compile(r"https?://\S+"), "[link hidden]"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email hidden]"),
    (re.compile(r"\b(?:sk|xox[a-z]?|ghp|gho)[-_][A-Za-z0-9_-]{8,}"), "[secret hidden]"),
    (re.compile(r"\b[A-Za-z0-9_+/=-]{32,}\b"), "[secret hidden]"),
]


def scrub(value) -> str:
    """Text for the page: secrets and emails hidden, then HTML-escaped."""
    text = "" if value is None else str(value)
    for pattern, replacement in _HIDE:
        text = pattern.sub(replacement, text)
    return escape(text)


def _table(headers: list[str], rows: list[list[str]], empty: str) -> str:
    if not rows:
        return f'<p class="empty">{escape(empty)}</p>'
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _badge(status: str) -> str:
    return f'<span class="badge {scrub(status)}">{scrub(status)}</span>'


def _hires(conn: sqlite3.Connection) -> str:
    day_one = {r["employee_id"]: r for r in metrics.day_one_rows(conn)}
    rows = []
    for e in conn.execute(
        """SELECT e.id, e.name, e.title, e.department, e.start_date,
                  COUNT(t.id) AS total, COUNT(t.completed_date) AS done
           FROM employees AS e LEFT JOIN onboarding_tasks AS t ON t.employee_id = e.id
           GROUP BY e.id ORDER BY e.start_date, e.name"""
    ):
        pct = round(100 * e["done"] / e["total"]) if e["total"] else 0
        d1 = day_one[e["id"]]
        d1_text = f"{d1['days_to_done']} days" if d1["days_to_done"] is not None else "not yet"
        rows.append([
            scrub(e["name"]), scrub(e["title"]), scrub(e["department"]), scrub(e["start_date"]),
            f'<div class="bar"><span style="width:{pct}%"></span></div>{e["done"]}/{e["total"]} done',
            f'{d1["day_one_done"]}/{d1["day_one_tasks"]} ({scrub(d1_text)})',
        ])
    return _table(["New hire", "Role", "Team", "Starts", "Task progress", "Day-one tasks (days from offer)"],
                  rows, "No hires yet.")


def _approvals(conn: sqlite3.Connection) -> str:
    rows = [
        [str(a["id"]), scrub(a["name"]), scrub(a["kind"]), _badge(a["status"]),
         scrub(a["decided_by"] or "-"), scrub(a["decided_at"] or "-"), scrub(a["reason"] or "-")]
        for a in conn.execute(
            """SELECT a.id, e.name, a.kind, a.status, a.decided_by, a.decided_at, a.reason
               FROM approvals AS a JOIN employees AS e ON e.id = a.employee_id ORDER BY a.id"""
        )
    ]
    return _table(["#", "New hire", "Kind", "Status", "Decided by", "Decided at", "Rejection reason"],
                  rows, "No approvals yet.")


def _overdue(conn: sqlite3.Connection, today: str) -> str:
    owners = metrics.overdue_by_owner(conn, today)
    summary = _table(
        ["Owner", "Overdue tasks", "Oldest due", "Days late"],
        [[scrub(o["owner_role"]), str(o["overdue_tasks"]), scrub(o["oldest_due"]), str(o["days_late"])] for o in owners],
        f"Nothing is overdue on {today}.",
    )
    tasks = metrics.overdue_tasks(conn, today)
    detail = _table(
        ["Owner", "New hire", "Task", "Due", "Days late"],
        [[scrub(t["owner_role"]), scrub(t["new_hire"]), scrub(t["task"]), scrub(t["due_date"]), str(t["days_late"])] for t in tasks],
        "",
    ) if tasks else ""
    return summary + (f"<details><summary>Every overdue task</summary>{detail}</details>" if tasks else "")


def _runs(conn: sqlite3.Connection) -> str:
    rows = [
        [str(r["id"]), scrub(r["ran_at"]), scrub(r["step"]), _badge(r["status"]), scrub((r["detail"] or "")[:300])]
        for r in conn.execute("SELECT id, ran_at, step, status, detail FROM runs_log ORDER BY id DESC LIMIT ?", (RUN_ROWS,))
    ]
    return _table(["#", "When (UTC)", "Step", "Status", "Detail"], rows, "Nothing has run yet.")


CSS = """
:root{--bg:#fff;--fg:#1c2330;--muted:#5b6575;--line:#d9dee7;--card:#f6f8fb;--bar:#2f6fed;--ok:#1b7f3b;--bad:#b42318;--warn:#9a6700}
@media (prefers-color-scheme:dark){:root{--bg:#10141b;--fg:#e6e9ef;--muted:#9aa4b4;--line:#2a3140;--card:#171c26;--bar:#6b9bff;--ok:#5fd082;--bad:#ff8a80;--warn:#e3b341}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px 48px}h1{margin:0 0 4px}h2{margin:32px 0 8px;font-size:1.15rem}
.sub{color:var(--muted);margin:0}.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%}th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--card);font-size:.8rem;text-transform:uppercase;letter-spacing:.03em;color:var(--muted)}tr:last-child td{border-bottom:0}
.bar{height:8px;background:var(--line);border-radius:4px;min-width:90px;margin-bottom:4px}.bar span{display:block;height:100%;background:var(--bar);border-radius:4px}
.badge{font-weight:600;font-size:.8rem;padding:1px 8px;border:1px solid currentColor;border-radius:10px}
.sent,.ok,.approved{color:var(--ok)}.failed,.rejected{color:var(--bad)}.pending,.skipped{color:var(--warn)}
.empty{color:var(--muted)}details{margin-top:10px}summary{cursor:pointer;color:var(--muted)}
"""


def build_html(conn: sqlite3.Connection, today: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Onboarding Agent dashboard</title><style>{CSS}</style></head>
<body><main>
<h1>Onboarding Agent</h1>
<p class="sub">Fictional company (Juniper Labs) and fictional people. Built from the demo database on {escape(today)}. Read-only: this page never calls any API.</p>
<h2>New hires and task progress</h2>{_hires(conn)}
<h2>Approvals</h2>{_approvals(conn)}
<h2>Overdue tasks by owner (as of {escape(today)})</h2>{_overdue(conn, today)}
<h2>Last {RUN_ROWS} runs</h2>{_runs(conn)}
</main></body></html>
"""


def write_dashboard(conn: sqlite3.Connection, out: str | Path, today: str | None = None) -> Path:
    """Write the page. `today` is chosen here in Python (UTC) and passed to SQL."""
    today = today or datetime.now(timezone.utc).date().isoformat()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(conn, today), encoding="utf-8")
    return out
