"""Company holidays in due dates, rescheduling open tasks, and a checklist rebuilt at send time.
Nothing here reaches Slack or Claude (conftest blocks both)."""
import shutil
from pathlib import Path

import pytest

from onboarding_agent import slack
from onboarding_agent.__main__ import main
from onboarding_agent.approvals import approve, create_draft, send_approved
from onboarding_agent.checklist import refresh_draft
from onboarding_agent.db import connect, init_db
from onboarding_agent.holidays import HolidayError, load_holidays
from onboarding_agent.onboard import due_date, process_event
from onboarding_agent.plan import KEY_VAR, draft_plan
from onboarding_agent.schedule import reschedule_open_tasks
from tests.test_slack import FAKE_URL, Recorder

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "sample_events"
HOLIDAYS = frozenset({"2026-12-24", "2026-12-25", "2026-12-31", "2027-01-01"})
PRIYA = SAMPLES / "cand_1003.json"


@pytest.fixture
def slack_on(monkeypatch):
    monkeypatch.setenv(slack.WEBHOOK_VAR, FAKE_URL)
    recorder = Recorder()
    monkeypatch.setattr(slack.requests, "post", recorder)
    return recorder


@pytest.fixture
def conn(tmp_path):
    c = connect(str(tmp_path / "t.db"))
    init_db(c)
    process_event(c, PRIYA)
    return c


def benefits(conn):
    return conn.execute("SELECT due_date, completed_date FROM onboarding_tasks WHERE task = 'Benefits enrollment'").fetchone()


# --- the rule -------------------------------------------------------------------------------

def test_priyas_benefits_enrollment_moves_from_dec_24_to_dec_23():
    assert due_date("2026-12-14", 10) == "2026-12-24"  # no holidays: Thursday
    assert due_date("2026-12-14", 10, HOLIDAYS) == "2026-12-23"  # Christmas Eve: previous working day


def test_holidays_skip_back_over_other_holidays_and_weekends():
    assert due_date("2026-12-14", 11, HOLIDAYS) == "2026-12-23"  # Dec 25 -> 24 is a holiday too -> 23
    assert due_date("2026-12-14", 17, HOLIDAYS) == "2026-12-30"  # Dec 31 -> Dec 30
    assert due_date("2026-12-14", 18, HOLIDAYS) == "2026-12-30"  # Jan 1 -> Dec 31 is a holiday -> Dec 30


def test_a_weekend_that_rolls_back_onto_a_holiday_keeps_going_back():
    # Sat Dec 26 before day one -> Friday Dec 25 (holiday) -> Dec 24 (holiday) -> Wed Dec 23
    assert due_date("2026-12-28", -2, HOLIDAYS) == "2026-12-23"


def test_a_weekend_that_rolls_forward_onto_a_monday_holiday_goes_to_the_previous_working_day():
    # Sun Dec 6 + forward roll = Monday Dec 7 (holiday here) -> back past the weekend to Friday Dec 4
    assert due_date("2026-12-04", 2, frozenset({"2026-12-07"})) == "2026-12-04"


def test_without_holidays_the_weekend_rules_are_unchanged():
    assert due_date("2026-12-07", 5) == "2026-12-14"
    assert due_date("2026-12-07", -2) == "2026-12-04"


def test_a_new_hire_loaded_from_the_event_gets_the_holiday_rule(conn):
    assert benefits(conn)["due_date"] == "2026-12-23"


def test_the_holidays_file_has_the_company_days():
    assert HOLIDAYS <= load_holidays()


def test_a_missing_or_broken_holidays_file_fails_loudly(tmp_path):
    with pytest.raises(HolidayError):
        load_holidays(tmp_path / "nope.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("- {date: 2026-13-45, name: nope}\n")
    with pytest.raises(HolidayError):
        load_holidays(bad)
    bad.write_text("just: a mapping\n")
    with pytest.raises(HolidayError):
        load_holidays(bad)


# --- reschedule -----------------------------------------------------------------------------

def make_stale(conn):
    conn.execute("UPDATE onboarding_tasks SET due_date = '2026-12-24' WHERE task = 'Benefits enrollment'")
    conn.commit()


def test_reschedule_moves_open_tasks_and_logs_old_and_new(conn):
    make_stale(conn)
    changes = reschedule_open_tasks(conn)
    assert [(c.task, c.old, c.new) for c in changes] == [("Benefits enrollment", "2026-12-24", "2026-12-23")]
    assert benefits(conn)["due_date"] == "2026-12-23"
    log = conn.execute("SELECT status, detail FROM runs_log WHERE step = 'reschedule cand_1003'").fetchall()
    assert [(r["status"], r["detail"]) for r in log] == [("ok", "Benefits enrollment: 2026-12-24 → 2026-12-23")]


def test_a_second_reschedule_changes_and_logs_nothing(conn):
    make_stale(conn)
    reschedule_open_tasks(conn)
    assert reschedule_open_tasks(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM runs_log WHERE step LIKE 'reschedule%'").fetchone()[0] == 1


def test_a_completed_task_is_never_rescheduled(conn):
    conn.execute("UPDATE onboarding_tasks SET due_date = '2026-12-24', completed_date = '2026-12-20' WHERE task = 'Benefits enrollment'")
    conn.commit()
    assert reschedule_open_tasks(conn) == []
    row = benefits(conn)
    assert (row["due_date"], row["completed_date"]) == ("2026-12-24", "2026-12-20")


def test_one_slack_summary_lists_each_task_hire_owner_and_dates(conn, slack_on):
    process_event(conn, SAMPLES / "cand_1002.json")  # Luis: his 30-day check-in is due Dec 31
    make_stale(conn)
    conn.execute("UPDATE onboarding_tasks SET due_date = '2026-12-31' WHERE task = '30-day check-in' AND employee_id = 2")
    conn.commit()
    reschedule_open_tasks(conn)
    assert len(slack_on.sent) == 1  # one summary per run, not one per task
    text = slack_on.sent[0]
    assert "Benefits enrollment for Priya Nair (New hire): 2026-12-24 → 2026-12-23" in text
    assert "30-day check-in for Luis Ortega (Manager): 2026-12-31 → 2026-12-30" in text


def test_nothing_is_posted_when_nothing_changes(conn, slack_on):
    assert reschedule_open_tasks(conn) == []
    assert slack_on.sent == []


def test_a_slack_failure_keeps_the_new_dates_and_is_logged(conn, monkeypatch):
    make_stale(conn)
    monkeypatch.setenv(slack.WEBHOOK_VAR, FAKE_URL)
    monkeypatch.setattr(slack.requests, "post", Recorder(status=500))
    reschedule_open_tasks(conn)
    assert benefits(conn)["due_date"] == "2026-12-23"
    assert conn.execute("SELECT status FROM runs_log WHERE step = 'notify reschedule'").fetchone()["status"] == "failed"


def test_run_onboarding_reschedules_and_does_not_redraft_priya(tmp_path, monkeypatch):
    # A folder with only Priya's event, a pending draft already saved, and a key set. If "run" tried to
    # draft again it would build a Claude client, and conftest makes that raise.
    folder = tmp_path / "events"
    folder.mkdir()
    shutil.copy(PRIYA, folder)
    db = str(tmp_path / "t.db")
    c = connect(db)
    init_db(c)
    process_event(c, PRIYA)
    draft = "Hi Priya\n\nYour checklist for the first two weeks:\n- 2026-12-24: Benefits enrollment (New hire)"
    approval_id = create_draft(c, 1, "first_week_plan", draft)
    make_stale(c)
    monkeypatch.setenv(KEY_VAR, "fake-key")
    assert main(["run", str(folder), "--db", db]) == 0
    c = connect(db)
    assert benefits(c)["due_date"] == "2026-12-23"
    rows = c.execute("SELECT id, status, draft FROM approvals").fetchall()
    assert [(r["id"], r["status"], r["draft"]) for r in rows] == [(approval_id, "pending", draft)]  # still pending, untouched
    assert c.execute("SELECT COUNT(*) FROM runs_log WHERE step LIKE 'claude call%'").fetchone()[0] == 0


# --- checklist built when sent --------------------------------------------------------------

def test_the_pending_message_says_the_dates_are_re_read_when_sent(conn):
    employee = conn.execute("SELECT * FROM employees").fetchone()
    text = slack.pending_message(1, employee, "draft")
    assert "re-read from the database" in text and "when the plan is sent" in text


def test_refresh_keeps_the_prose_and_rebuilds_the_checklist(conn):
    employee = conn.execute("SELECT * FROM employees").fetchone()
    stale = "Hi Priya,\n\nWelcome!\n\nYour checklist for the first two weeks:\n- 2026-12-24: Benefits enrollment (New hire)"
    fresh = refresh_draft(conn, stale, employee)
    assert fresh.startswith("Hi Priya,\n\nWelcome!\n\nYour checklist for the first two weeks:")
    assert "2026-12-23: Benefits enrollment" in fresh and "2026-12-24" not in fresh
    assert refresh_draft(conn, "no checklist here", employee) == "no checklist here"


def test_an_approved_plan_is_sent_with_current_dates_and_the_stored_draft_is_unchanged(conn, capsys):
    make_stale(conn)
    approval_id = draft_plan(conn, "cand_1003")  # no key: a labeled sample plan whose checklist says Dec 24
    stored = conn.execute("SELECT draft FROM approvals WHERE id = ?", (approval_id,)).fetchone()["draft"]
    assert "2026-12-24: Benefits enrollment" in stored
    approve(conn, approval_id, "Eli Moss")
    reschedule_open_tasks(conn)  # the dates move after approval
    capsys.readouterr()
    send_approved(conn, approval_id, slack.slack_sender)
    sent = capsys.readouterr().out
    assert "2026-12-23: Benefits enrollment" in sent and "2026-12-24" not in sent
    assert "approved by Eli Moss" in sent
    assert conn.execute("SELECT draft FROM approvals WHERE id = ?", (approval_id,)).fetchone()["draft"] == stored
    assert "refreshed" in conn.execute("SELECT detail FROM runs_log WHERE step = ?", (f"send approval {approval_id}",)).fetchone()["detail"]
