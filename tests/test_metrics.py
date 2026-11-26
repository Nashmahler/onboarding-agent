"""Day-one metric, overdue-by-owner, and the complete command. Fixed dates, no network."""
from pathlib import Path

import pytest

from onboarding_agent import metrics, slack
from onboarding_agent.__main__ import main
from onboarding_agent.db import connect, init_db
from onboarding_agent.onboard import process_event
from onboarding_agent.tasks import TaskError, complete_task

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "sample_events"


@pytest.fixture
def conn(tmp_path):
    c = connect(str(tmp_path / "t.db"))
    init_db(c)
    process_event(c, SAMPLES / "cand_1001.json")
    return c


def maya(conn):
    return next(r for r in metrics.day_one_rows(conn) if r["new_hire"] == "Maya Chen")


def day_one_tasks(conn):
    return [r["task"] for r in conn.execute(
        """SELECT t.task FROM onboarding_tasks t JOIN employees e ON e.id = t.employee_id
           WHERE t.due_date <= e.start_date ORDER BY t.id""")]


def test_day_one_is_not_yet_until_every_day_one_task_is_done(conn):
    assert maya(conn)["days_to_done"] is None
    tasks = day_one_tasks(conn)
    for task in tasks[:-1]:
        complete_task(conn, "cand_1001", task, "Eli", today="2026-11-20")
    row = maya(conn)
    assert row["days_to_done"] is None and row["day_one_done"] == len(tasks) - 1


def test_days_to_done_counts_from_offer_to_the_last_day_one_task(conn):
    offer = conn.execute("SELECT offer_accepted_date FROM employees").fetchone()[0]
    for task in day_one_tasks(conn):
        complete_task(conn, "cand_1001", task, "Eli", today="2026-11-20")
    expected = (__import__("datetime").date.fromisoformat("2026-11-20") - __import__("datetime").date.fromisoformat(offer)).days
    assert maya(conn)["days_to_done"] == expected


def test_tasks_due_after_the_start_date_are_not_day_one(conn):
    after = conn.execute("SELECT COUNT(*) FROM onboarding_tasks t JOIN employees e ON e.id = t.employee_id WHERE t.due_date > e.start_date").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM onboarding_tasks").fetchone()[0]
    assert after > 0 and maya(conn)["day_one_tasks"] == total - after


def test_complete_sets_the_date_in_code_and_logs_it(conn):
    day = complete_task(conn, "cand_1001", "Add to payroll", "Pat", today="2026-11-19")
    assert day == "2026-11-19"
    assert conn.execute("SELECT completed_date FROM onboarding_tasks WHERE task = 'Add to payroll'").fetchone()[0] == "2026-11-19"
    log = conn.execute("SELECT status, detail FROM runs_log WHERE step = 'complete cand_1001'").fetchone()
    assert log["status"] == "ok" and "Pat" in log["detail"]


def test_a_completed_task_is_no_longer_overdue(conn):
    before = {r["owner_role"]: r["overdue_tasks"] for r in metrics.overdue_by_owner(conn, "2026-12-31")}
    complete_task(conn, "cand_1001", "Add to payroll", "Pat", today="2026-11-19")
    after = {r["owner_role"]: r["overdue_tasks"] for r in metrics.overdue_by_owner(conn, "2026-12-31")}
    assert after.get("Payroll", 0) == before["Payroll"] - 1  # Maya has one Payroll task: owner drops out


@pytest.mark.parametrize("candidate, task, by", [
    ("cand_nope", "Add to payroll", "Pat"),   # unknown hire
    ("cand_1001", "Water the plants", "Pat"),  # unknown task
    ("cand_1001", "Add to payroll", "  "),     # nobody named
])
def test_complete_refuses_bad_input_without_changing_anything(conn, candidate, task, by):
    with pytest.raises(TaskError):
        complete_task(conn, candidate, task, by)
    assert conn.execute("SELECT COUNT(*) FROM onboarding_tasks WHERE completed_date IS NOT NULL").fetchone()[0] == 0


def test_completing_twice_keeps_the_first_date_and_logs_a_failure(conn):
    complete_task(conn, "cand_1001", "Add to payroll", "Pat", today="2026-11-19")
    with pytest.raises(TaskError, match="already completed on 2026-11-19"):
        complete_task(conn, "cand_1001", "Add to payroll", "Sam", today="2026-11-25")
    assert conn.execute("SELECT completed_date FROM onboarding_tasks WHERE task = 'Add to payroll'").fetchone()[0] == "2026-11-19"
    assert conn.execute("SELECT COUNT(*) FROM runs_log WHERE step = 'complete cand_1001' AND status = 'failed'").fetchone()[0] == 1


def test_complete_posts_a_short_slack_note(conn, monkeypatch, capsys):
    complete_task(conn, "cand_1001", "Add to payroll", "Pat", today="2026-11-19")
    out = capsys.readouterr().out
    assert "Add to payroll" in out and "Maya Chen" in out and "Pat" in out


def test_complete_cli_and_metrics_cli(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    assert main(["load", str(SAMPLES), "--db", db]) == 1  # cand_1005 fails on purpose
    assert main(["complete", "cand_1001", "--task", "Add to payroll", "--by", "Pat", "--db", db]) == 0
    assert main(["complete", "cand_1001", "--task", "Add to payroll", "--by", "Pat", "--db", db]) == 1
    capsys.readouterr()
    assert main(["metrics", "--today", "2026-11-26", "--db", db]) == 0
    assert "Maya Chen: not yet" in capsys.readouterr().out
