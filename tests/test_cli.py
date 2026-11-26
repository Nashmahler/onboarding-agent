import shutil
from pathlib import Path

from onboarding_agent.__main__ import main
from onboarding_agent.db import connect

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "sample_events"


def query(db, sql):
    return connect(str(db)).execute(sql).fetchall()


def test_load_runs_every_event_and_reports_the_failure(tmp_path, capsys):
    db = tmp_path / "test.db"
    code = main(["load", str(SAMPLES), "--db", str(db)])
    out = capsys.readouterr()
    assert code == 1  # cand_1005 failed
    assert "cand_1005_missing_start_date.json" in out.out and "failed" in out.out
    assert "1 event(s) failed" in out.err
    assert query(db, "SELECT COUNT(*) FROM employees")[0][0] == 4
    assert query(db, "SELECT COUNT(*) FROM onboarding_tasks")[0][0] == 39


def test_running_load_twice_adds_nothing(tmp_path):
    db = tmp_path / "test.db"
    main(["load", str(SAMPLES), "--db", str(db)])
    main(["load", str(SAMPLES), "--db", str(db)])
    assert query(db, "SELECT COUNT(*) FROM employees")[0][0] == 4
    assert query(db, "SELECT COUNT(*) FROM onboarding_tasks")[0][0] == 39
    assert query(db, "SELECT COUNT(*) FROM runs_log")[0][0] == 10  # every run is logged


def test_clean_folder_exits_zero(tmp_path):
    folder = tmp_path / "events"
    folder.mkdir()
    shutil.copy(SAMPLES / "cand_1001.json", folder)
    assert main(["load", str(folder), "--db", str(tmp_path / "t.db")]) == 0


def test_missing_folder_exits_two(tmp_path, capsys):
    assert main(["load", str(tmp_path / "nope"), "--db", str(tmp_path / "t.db")]) == 2
    assert "not a folder" in capsys.readouterr().err


def loaded_db(tmp_path, monkeypatch):
    """A database with the sample hires, and no API key so Claude can never be called."""
    monkeypatch.delenv("ONBOARDING_API_KEY", raising=False)
    db = tmp_path / "test.db"
    main(["load", str(SAMPLES), "--db", str(db)])
    return db


def test_draft_approve_send_flow(tmp_path, monkeypatch, capsys):
    db = loaded_db(tmp_path, monkeypatch)
    assert main(["draft", "cand_1001", "--db", str(db)]) == 0
    assert "[SAMPLE PLAN" in capsys.readouterr().out
    assert query(db, "SELECT status FROM approvals")[0][0] == "pending"

    assert main(["approve", "1", "--by", "Eli Moss", "--db", str(db)]) == 0
    assert main(["send", "1", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "Welcome to Juniper Labs, Maya Chen" in out  # no webhook: printed to the console
    row = query(db, "SELECT status, decided_by FROM approvals")[0]
    assert (row[0], row[1]) == ("sent", "Eli Moss")


def test_send_before_approval_is_refused_and_prints_nothing(tmp_path, monkeypatch, capsys):
    db = loaded_db(tmp_path, monkeypatch)
    main(["draft", "cand_1001", "--db", str(db)])
    capsys.readouterr()
    assert main(["send", "1", "--db", str(db)]) == 1
    out = capsys.readouterr()
    assert "not approved" in out.err
    assert "To:" not in out.out and "SAMPLE" not in out.out  # the draft was not delivered
    assert query(db, "SELECT status FROM approvals")[0][0] == "pending"


def test_reject_then_send_is_refused(tmp_path, monkeypatch, capsys):
    db = loaded_db(tmp_path, monkeypatch)
    main(["draft", "cand_1001", "--db", str(db)])
    main(["reject", "1", "--by", "Eli Moss", "--db", str(db)])
    capsys.readouterr()
    assert main(["send", "1", "--db", str(db)]) == 1
    assert "To:" not in capsys.readouterr().out


def test_approve_requires_by():
    import pytest

    with pytest.raises(SystemExit):
        main(["approve", "1"])
