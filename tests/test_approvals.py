from pathlib import Path

import pytest

from onboarding_agent.approvals import (
    ApprovalError,
    NotApprovedError,
    approve,
    create_draft,
    get_approval,
    reject,
    send_approved,
)
from onboarding_agent.db import connect, init_db
from onboarding_agent.onboard import process_event

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "sample_events"


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_db(c)
    process_event(c, SAMPLES / "cand_1001.json")
    return c


@pytest.fixture
def sent():
    """A fake sender that records every delivery, so tests can prove nothing went out."""
    calls = []
    return calls, lambda approval, employee: calls.append(approval["id"])


def new_draft(conn):
    employee_id = conn.execute("SELECT id FROM employees").fetchone()["id"]
    return create_draft(conn, employee_id, "first_week_plan", "Welcome, Maya!")


def status(conn, approval_id):
    return get_approval(conn, approval_id)["status"]


def test_new_drafts_are_always_pending(conn):
    assert status(conn, new_draft(conn)) == "pending"


def test_pending_draft_cannot_be_sent(conn, sent):
    calls, sender = sent
    approval_id = new_draft(conn)
    with pytest.raises(NotApprovedError):
        send_approved(conn, approval_id, sender)
    assert calls == []  # the sender was never reached
    assert status(conn, approval_id) == "pending"


def test_rejected_draft_cannot_be_sent(conn, sent):
    calls, sender = sent
    approval_id = new_draft(conn)
    reject(conn, approval_id, "Eli Moss")
    with pytest.raises(NotApprovedError):
        send_approved(conn, approval_id, sender)
    assert calls == []
    assert status(conn, approval_id) == "rejected"


def test_approved_draft_sends_once_and_only_once(conn, sent):
    calls, sender = sent
    approval_id = new_draft(conn)
    approve(conn, approval_id, "Eli Moss")
    send_approved(conn, approval_id, sender)
    assert calls == [approval_id]
    assert status(conn, approval_id) == "sent"
    with pytest.raises(NotApprovedError):  # a second send is refused
        send_approved(conn, approval_id, sender)
    assert calls == [approval_id]


def test_unknown_id_is_refused(conn, sent):
    calls, sender = sent
    with pytest.raises(ApprovalError):
        send_approved(conn, 999, sender)
    with pytest.raises(ApprovalError):
        approve(conn, 999, "Eli Moss")
    assert calls == []


def test_approval_records_who_and_when(conn):
    approval_id = new_draft(conn)
    approve(conn, approval_id, "Eli Moss")
    row = get_approval(conn, approval_id)
    assert row["decided_by"] == "Eli Moss"
    assert row["decided_at"]


@pytest.mark.parametrize("name", ["", "   ", None])
def test_approving_needs_a_name(conn, name):
    approval_id = new_draft(conn)
    with pytest.raises(ApprovalError):
        approve(conn, approval_id, name)
    assert status(conn, approval_id) == "pending"


def test_a_decision_is_final(conn):
    approval_id = new_draft(conn)
    reject(conn, approval_id, "Eli Moss")
    with pytest.raises(ApprovalError):  # rejected can't be approved later
        approve(conn, approval_id, "Eli Moss")
    assert status(conn, approval_id) == "rejected"


def test_failed_delivery_goes_back_to_approved_and_is_logged(conn):
    approval_id = new_draft(conn)
    approve(conn, approval_id, "Eli Moss")

    def broken_sender(approval, employee):
        raise RuntimeError("slack is down")

    with pytest.raises(RuntimeError):
        send_approved(conn, approval_id, broken_sender)
    assert status(conn, approval_id) == "approved"  # can be retried
    log = conn.execute(
        "SELECT status, detail FROM runs_log WHERE step = ?", (f"send approval {approval_id}",)
    ).fetchall()
    assert [r["status"] for r in log] == ["failed"]
    assert "slack is down" in log[0]["detail"]


def test_refused_send_is_logged(conn, sent):
    _, sender = sent
    approval_id = new_draft(conn)
    with pytest.raises(NotApprovedError):
        send_approved(conn, approval_id, sender)
    row = conn.execute(
        "SELECT status, detail FROM runs_log WHERE step = ?", (f"send approval {approval_id}",)
    ).fetchone()
    assert row["status"] == "failed" and "pending" in row["detail"]
