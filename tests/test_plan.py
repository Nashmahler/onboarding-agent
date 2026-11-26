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

    def __init__(self, text="Welcome to the team, Maya! Looking forward to week one.", error=None, stop_reason="end_turn"):
        self.stop_reason = stop_reason
        self.calls = []
        self.error = error
        self.messages = SimpleNamespace(create=self._create)
        self._text = text

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self._text)], stop_reason=self.stop_reason
        )


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


# --- Redraft after rejection, and the cap of 3 Claude calls per hire ---
from onboarding_agent.approvals import reject
from onboarding_agent.plan import CallLimitError, MAX_CALLS_PER_HIRE


def calls_logged(conn, candidate_id):
    return conn.execute(
        "SELECT COUNT(*) FROM runs_log WHERE step = ?", (f"claude call {candidate_id}",)
    ).fetchone()[0]


def test_new_draft_allowed_after_rejection(conn):
    client = FakeClient()
    first = draft_plan(conn, "cand_1001", client=client)
    reject(conn, first, "Eli Moss")
    second = draft_plan(conn, "cand_1001", client=client)
    assert second != first
    assert get_approval(conn, second)["status"] == "pending"
    assert len(client.calls) == 2


def test_fourth_call_is_refused(conn):
    client = FakeClient()
    for _ in range(MAX_CALLS_PER_HIRE):
        reject(conn, draft_plan(conn, "cand_1001", client=client), "Eli Moss")
    with pytest.raises(CallLimitError):
        draft_plan(conn, "cand_1001", client=client)
    assert len(client.calls) == 3  # the 4th never reached Claude
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 3
    assert calls_logged(conn, "cand_1001") == 3
    log = conn.execute("SELECT status, detail FROM runs_log WHERE step = 'draft cand_1001' ORDER BY id DESC").fetchone()
    assert log["status"] == "failed" and "3 Claude calls" in log["detail"]


def test_limit_refusal_never_builds_a_real_client(conn, monkeypatch):
    client = FakeClient()
    for _ in range(3):
        reject(conn, draft_plan(conn, "cand_1001", client=client), "Eli Moss")
    monkeypatch.setenv(plan.KEY_VAR, "test-key-not-real")  # a key is set, but the cap still wins
    with pytest.raises(CallLimitError):  # autouse fixture would raise AssertionError if a client were built
        draft_plan(conn, "cand_1001")


def test_cap_is_per_hire(conn):
    process_event(conn, SAMPLES / "cand_1002.json")
    client = FakeClient()
    for _ in range(3):
        reject(conn, draft_plan(conn, "cand_1001", client=client), "Eli Moss")
    other = draft_plan(conn, "cand_1002", client=client)  # a different hire is unaffected
    assert get_approval(conn, other)["status"] == "pending"
    assert calls_logged(conn, "cand_1002") == 1


def test_failed_calls_still_use_a_slot(conn):
    broken = FakeClient(error=RuntimeError("network down"))
    for _ in range(3):
        with pytest.raises(PlanError):
            draft_plan(conn, "cand_1001", client=broken)
    with pytest.raises(CallLimitError):
        draft_plan(conn, "cand_1001", client=FakeClient())


def test_rerunning_with_a_live_draft_costs_no_call(conn):
    client = FakeClient()
    draft_plan(conn, "cand_1001", client=client)
    draft_plan(conn, "cand_1001", client=client)
    assert calls_logged(conn, "cand_1001") == 1


def test_cut_off_reply_is_a_failure_saves_nothing_and_still_counts(conn):
    client = FakeClient(text="Hi Maya, we're excited", stop_reason="max_tokens")
    with pytest.raises(PlanError, match="cut off"):
        draft_plan(conn, "cand_1001", client=client)
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0  # no approval row
    log = conn.execute("SELECT status, detail FROM runs_log WHERE step = 'draft cand_1001'").fetchone()
    assert log["status"] == "failed" and "cut off" in log["detail"]
    assert calls_logged(conn, "cand_1001") == 1  # the call still used a slot
    assert client.calls[0]["max_tokens"] == 2000
