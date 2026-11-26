"""Slack behaviour, with a fake webhook and a recorder. Nothing here can reach the network:
conftest.py makes any real HTTP request raise."""
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from onboarding_agent import slack
from onboarding_agent.__main__ import main
from onboarding_agent.approvals import approve, create_draft, send_approved
from onboarding_agent.db import connect, init_db
from onboarding_agent.onboard import log_run, process_event
from onboarding_agent.plan import draft_plan

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "sample_events"
FAKE_URL = "https://hooks.example.invalid/services/SECRET-PART-123"


class Recorder:
    def __init__(self, status=200, error=None):
        self.sent, self.status, self.error = [], status, error

    def __call__(self, url, json=None, timeout=None):
        if self.error:
            raise self.error
        self.sent.append(json["text"])
        return SimpleNamespace(ok=self.status < 400, status_code=self.status)


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
    process_event(c, SAMPLES / "cand_1001.json")
    return c


def test_without_a_webhook_it_prints_to_the_console(capsys):
    assert slack.post("hello") is False
    assert "hello" in capsys.readouterr().out


def test_with_a_webhook_it_posts_the_text(slack_on):
    assert slack.post("hello") is True
    assert slack_on.sent == ["hello"]


def test_errors_never_contain_the_webhook_url(monkeypatch):
    monkeypatch.setenv(slack.WEBHOOK_VAR, FAKE_URL)
    monkeypatch.setattr(slack.requests, "post", Recorder(error=requests.ConnectionError(f"failed to reach {FAKE_URL}")))
    with pytest.raises(slack.SlackError) as excinfo:
        slack.post("x")
    assert "SECRET-PART" not in str(excinfo.value) and "SECRET-PART" not in repr(excinfo.value.__cause__)
    monkeypatch.setattr(slack.requests, "post", Recorder(status=500))
    with pytest.raises(slack.SlackError, match="HTTP 500"):
        slack.post("x")


def test_text_from_outside_is_escaped():
    assert slack.escape("a <b> & c") == "a &lt;b&gt; &amp; c"


def test_draft_posts_pending_message_with_the_approval_id(conn, slack_on):
    approval_id = draft_plan(conn, "cand_1001")
    message = slack_on.sent[0]
    assert f"pending approval #{approval_id}" in message and "Maya Chen" in message
    assert "Nothing has been sent to the new hire" in message


def test_a_slack_outage_does_not_lose_the_draft(conn, monkeypatch, capsys):
    monkeypatch.setenv(slack.WEBHOOK_VAR, FAKE_URL)
    monkeypatch.setattr(slack.requests, "post", Recorder(status=500))
    approval_id = draft_plan(conn, "cand_1001")
    assert conn.execute("SELECT status FROM approvals WHERE id = ?", (approval_id,)).fetchone()[0] == "pending"
    failed = conn.execute("SELECT step FROM runs_log WHERE status = 'failed'").fetchall()
    assert f"notify pending approval {approval_id}" in [r[0] for r in failed]


def test_a_failed_step_is_logged_and_alerts_slack(conn, slack_on):
    log_run(conn, "onboard cand_1005_missing_start_date.json", "failed", "missing field: offer.start_date")
    row = conn.execute("SELECT status FROM runs_log WHERE step LIKE 'onboard cand_1005%'").fetchone()
    assert row[0] == "failed"  # logged
    assert len(slack_on.sent) == 1
    assert "Step failed" in slack_on.sent[0] and "offer.start_date" in slack_on.sent[0]


def test_ok_and_skipped_steps_do_not_alert(conn, slack_on):
    log_run(conn, "a", "ok", "fine")
    log_run(conn, "b", "skipped", "nothing to do")
    assert slack_on.sent == []


def test_a_bad_event_in_load_alerts_and_still_logs(tmp_path, slack_on):
    db = tmp_path / "t.db"
    assert main(["load", str(SAMPLES), "--db", str(db)]) == 1
    assert sum("cand_1005" in m and "Step failed" in m for m in slack_on.sent) == 1
    logged = connect(str(db)).execute("SELECT detail FROM runs_log WHERE status = 'failed'").fetchall()
    assert len(logged) == 1 and "start_date" in logged[0][0]


def test_an_undeliverable_alert_is_recorded_not_silent(conn, monkeypatch, capsys):
    monkeypatch.setenv(slack.WEBHOOK_VAR, FAKE_URL)
    monkeypatch.setattr(slack.requests, "post", Recorder(status=500))
    log_run(conn, "some step", "failed", "boom")
    assert "could not deliver the alert" in capsys.readouterr().err
    steps = [r[0] for r in conn.execute("SELECT step FROM runs_log WHERE status = 'failed'")]
    assert steps == ["some step", slack.ALERT_FAILED_STEP]


def test_approved_plan_goes_to_slack_only_after_approval(conn, slack_on):
    approval_id = create_draft(conn, 1, "first_week_plan", "Hi Maya, here is your plan.")
    with pytest.raises(Exception):
        send_approved(conn, approval_id, slack.slack_sender)
    assert not any("Welcome" in m for m in slack_on.sent)  # a pending draft never reached Slack
    approve(conn, approval_id, "Eli Moss")
    send_approved(conn, approval_id, slack.slack_sender)
    welcomes = [m for m in slack_on.sent if "Welcome to Juniper Labs" in m]
    assert len(welcomes) == 1 and "Maya Chen" in welcomes[0]
    assert "approved by Eli Moss" in welcomes[0] and "Hi Maya, here is your plan." in welcomes[0]


def test_a_failed_slack_send_leaves_the_draft_approved(conn, monkeypatch):
    approval_id = create_draft(conn, 1, "first_week_plan", "plan")
    approve(conn, approval_id, "Eli Moss")
    monkeypatch.setenv(slack.WEBHOOK_VAR, FAKE_URL)
    monkeypatch.setattr(slack.requests, "post", Recorder(status=500))
    with pytest.raises(slack.SlackError):
        send_approved(conn, approval_id, slack.slack_sender)
    assert conn.execute("SELECT status FROM approvals").fetchone()[0] == "approved"


def test_approve_with_send_flag(tmp_path, slack_on):
    db = tmp_path / "t.db"
    folder = tmp_path / "events"
    folder.mkdir()
    shutil.copy(SAMPLES / "cand_1001.json", folder)
    main(["load", str(folder), "--db", str(db)])
    main(["draft", "cand_1001", "--db", str(db)])
    assert main(["approve", "1", "--by", "Eli Moss", "--send", "--db", str(db)]) == 0
    assert connect(str(db)).execute("SELECT status FROM approvals").fetchone()[0] == "sent"
    assert any("Welcome to Juniper Labs" in m for m in slack_on.sent)


def test_run_command_passes_when_every_failure_was_alerted(tmp_path, slack_on):
    db = tmp_path / "t.db"
    assert main(["run", str(SAMPLES), "--db", str(db)]) == 0  # cand_1005 fails on purpose
    pending = [m for m in slack_on.sent if "pending approval" in m]
    assert len(pending) == 4
    assert sum("Step failed" in m and "cand_1005" in m for m in slack_on.sent) == 1
    # Running it again drafts nothing new (no new Claude calls, no new pending messages).
    before = len(slack_on.sent)
    assert main(["run", str(SAMPLES), "--db", str(db)]) == 0
    assert not [m for m in slack_on.sent[before:] if "pending approval" in m]
    assert connect(str(db)).execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 4


def test_run_command_fails_when_an_alert_cannot_be_delivered(tmp_path, monkeypatch):
    monkeypatch.setenv(slack.WEBHOOK_VAR, FAKE_URL)
    monkeypatch.setattr(slack.requests, "post", Recorder(status=500))
    assert main(["run", str(SAMPLES), "--db", str(tmp_path / "t.db")]) == 1


def test_run_command_fails_on_an_unexpected_crash(tmp_path, monkeypatch):
    monkeypatch.setattr("onboarding_agent.__main__.process_event", lambda *a: 1 / 0)
    db = tmp_path / "t.db"
    assert main(["run", str(SAMPLES), "--db", str(db)]) == 1
    detail = connect(str(db)).execute("SELECT detail FROM runs_log WHERE step = 'run onboarding'").fetchone()[0]
    assert "ZeroDivisionError" in detail
