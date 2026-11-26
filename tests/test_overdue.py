from pathlib import Path

from onboarding_agent import overdue
from onboarding_agent.__main__ import main
from onboarding_agent.db import connect, init_db
from onboarding_agent.onboard import process_event

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "sample_events"
TODAY = "2026-11-26"  # a fixed day: tests never depend on the real date


def loaded(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_db(conn)
    for path in sorted(SAMPLES.glob("*.json")):
        process_event(conn, path)
    return conn


def by_owner(conn, today=TODAY):
    rows = overdue._query(conn, "overdue_by_owner.sql", today)
    return [(r["owner_role"], r["overdue_tasks"], r["oldest_due"], r["days_late"]) for r in rows]


def test_overdue_counts_grouped_by_owner(tmp_path):
    conn = loaded(tmp_path)
    assert by_owner(conn) == [
        ("IT", 2, "2026-11-23", 3),
        ("Payroll", 2, "2026-11-23", 3),
        ("People Ops", 2, "2026-11-20", 6),
    ]


def test_a_task_due_today_is_not_overdue_but_tomorrow_it_is(tmp_path):
    conn = loaded(tmp_path)
    # IT's laptop task is due 2026-11-23: not overdue on that day, one day late the next.
    assert "IT" not in [r[0] for r in by_owner(conn, "2026-11-23")]
    assert ("IT", 1, "2026-11-23", 1) in by_owner(conn, "2026-11-24")


def test_completed_tasks_are_not_overdue(tmp_path):
    conn = loaded(tmp_path)
    with conn:
        conn.execute(
            "UPDATE onboarding_tasks SET completed_date = '2026-11-25' WHERE owner_role = 'Payroll'"
        )
    assert "Payroll" not in [r[0] for r in by_owner(conn)]


def test_nothing_overdue_before_any_due_date(tmp_path):
    conn = loaded(tmp_path)
    assert by_owner(conn, "2026-01-01") == []
    assert "nothing is overdue" in overdue.build_report(conn, "2026-01-01")


def test_report_lists_each_task_under_its_owner(tmp_path):
    report = overdue.build_report(loaded(tmp_path), TODAY)
    assert report.splitlines()[0] == "Overdue report for 2026-11-26: 6 open task(s) past due"
    assert "People Ops: 2 overdue (oldest 6 days late)" in report
    assert "  - Send offer paperwork and I-9 link for " in report


def test_cli_overdue_prints_and_logs_without_posting(tmp_path, capsys, monkeypatch):
    db = tmp_path / "t.db"
    loaded(tmp_path)
    assert main(["overdue", "--today", TODAY, "--db", str(db)]) == 0
    assert "6 open task(s) past due" in capsys.readouterr().out
    steps = connect(str(db)).execute("SELECT step, status FROM runs_log WHERE step = 'overdue report'").fetchall()
    assert [tuple(r) for r in steps] == [("overdue report", "ok")]
