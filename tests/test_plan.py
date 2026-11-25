from pathlib import Path
from types import SimpleNamespace

import pytest

from onboarding_agent import plan
from onboarding_agent.approvals import get_approval
from onboarding_agent.db import connect, init_db
from onboarding_agent.onboard import process_event
from onboarding_agent.plan import PlanError, draft_plan

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "sample_events"


class FakeClient:
    """Stands in for the Anthropic client. Counts calls; never touches the network."""

    def __init__(self, text="Welcome to the team, Maya! Looking forward to week one.", error=None):
        self.calls = []
        self.error = error
        self.messages = SimpleNamespace(create=self._create)
        self._text = text

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._text)])


@pytest.fixture(autouse=True)
def no_real_api(monkeypatch):
    """Safety net: tests can never build a real client or see a real key."""
    monkeypatch.delenv(plan.KEY_VAR, raising=False)

    def boom(api_key):
        raise AssertionError("a test tried to create the real Anthropic client")

    monkeypatch.setattr(plan, "_make_client", boom)


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_db(c)
    process_event(c, SAMPLES / "cand_1001.json")  # Maya Chen, starts 2026-12-07
    return c


def test_draft_is_saved_pending_with_code_computed_dates(conn):
    client = FakeClient()
    approval_id = draft_plan(conn, "cand_1001", client=client)
    row = get_approval(conn, approval_id)
    assert row["status"] == "pending" and row["kind"] == "first_week_plan"
    assert "Welcome to the team, Maya!" in row["draft"]
    # Maya starts 2026-12-07; "Security training" is due 2026-12-14 (a Monday, day 7).
    assert "- 2026-12-14: Security training (New hire)" in row["draft"]
    assert "- 2026-12-17: Benefits enrollment (New hire)" in row["draft"]  # day 10, inside the window
    assert "30-day check-in" not in row["draft"]  # due 2027-01-06, well outside
    assert "Order and ship laptop" not in row["draft"]  # pre-start, not part of week one-two


def test_prompt_forbids_dates_and_has_no_email_addresses(conn):
    client = FakeClient()
    draft_plan(conn, "cand_1001", client=client)
    prompt = client.calls[0]["messages"][0]["content"]
    assert "do not write any dates" in prompt
    assert "@" not in prompt  # only role, team, location and manager name are sent


def test_running_draft_twice_makes_one_call_and_one_row(conn):
    client = FakeClient()
    first = draft_plan(conn, "cand_1001", client=client)
    second = draft_plan(conn, "cand_1001", client=client)
    assert first == second
    assert len(client.calls) == 1
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 1


def test_no_key_saves_a_labeled_sample_and_never_builds_a_client(conn):
    approval_id = draft_plan(conn, "cand_1001")  # autouse fixture makes _make_client explode
    draft = get_approval(conn, approval_id)["draft"]
    assert draft.startswith("[SAMPLE PLAN")
    assert get_approval(conn, approval_id)["status"] == "pending"
    log = conn.execute("SELECT status FROM runs_log WHERE step = 'draft cand_1001'").fetchone()
    assert log["status"] == "skipped"


def test_failed_call_saves_nothing_and_is_logged(conn):
    client = FakeClient(error=RuntimeError("network down"))
    with pytest.raises(PlanError):
        draft_plan(conn, "cand_1001", client=client)
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
    log = conn.execute("SELECT status, detail FROM runs_log WHERE step = 'draft cand_1001'").fetchone()
    assert log["status"] == "failed" and "network down" in log["detail"]


def test_empty_reply_is_a_failure(conn):
    with pytest.raises(PlanError):
        draft_plan(conn, "cand_1001", client=FakeClient(text="   "))
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0


def test_unknown_candidate_fails_and_is_logged(conn):
    with pytest.raises(PlanError):
        draft_plan(conn, "cand_nope", client=FakeClient())
    assert conn.execute("SELECT status FROM runs_log WHERE step = 'draft cand_nope'").fetchone()["status"] == "failed"


def test_real_key_is_passed_explicitly(conn, monkeypatch):
    seen = {}
    client = FakeClient()

    def fake_make(api_key):
        seen["key"] = api_key
        return client

    monkeypatch.setattr(plan, "_make_client", fake_make)
    monkeypatch.setenv(plan.KEY_VAR, "test-key-not-real")
    draft_plan(conn, "cand_1001")
    assert seen["key"] == "test-key-not-real" and len(client.calls) == 1
