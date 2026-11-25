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
