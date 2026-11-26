"""The dashboard page: right content, no emails or secrets, never touches the network."""
import ast
import re
from pathlib import Path

from onboarding_agent import dashboard
from onboarding_agent.__main__ import main
from onboarding_agent.approvals import approve, create_draft, reject
from onboarding_agent.db import connect, init_db
from onboarding_agent.onboard import log_run, process_event
from onboarding_agent.tasks import complete_task

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "sample_events"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
TODAY = "2026-11-26"


def loaded(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_db(conn)
    for path in sorted(SAMPLES.glob("*.json")):
        process_event(conn, path)
    return conn


def page(conn):
    return dashboard.build_html(conn, TODAY)


def test_page_shows_hires_approvals_overdue_and_runs(tmp_path):
    conn = loaded(tmp_path)
    complete_task(conn, "cand_1001", "Add to payroll", "Pat", today="2026-11-19")
    a, b = (create_draft(conn, i, "first_week_plan", "draft text") for i in (1, 2))
    approve(conn, a, "Eli Moss")
    reject(conn, b, "Eli Moss", "Invented a job title")
    html = page(conn)
    assert "Maya Chen" in html and "1/" in html  # progress shows the completed task
    assert "approved" in html and "rejected" in html and "Eli Moss" in html and "Invented a job title" in html
    assert "Payroll" in html and "People Ops" in html  # overdue by owner
    assert "onboard cand_1005_missing_start_date.json" in html  # a runs_log row
    assert "not yet" in html  # day-one metric for a hire still waiting


def test_page_shows_only_the_last_20_runs(tmp_path):
    conn = loaded(tmp_path)
    for i in range(30):
        log_run(conn, f"marker step {i:02d}", "ok", "x")
    html = page(conn)
    assert "marker step 29" in html and "marker step 10" in html
    assert "marker step 09" not in html


def test_page_contains_no_emails_or_secrets(tmp_path):
    conn = loaded(tmp_path)
    secret_key = "sk-ant-api03-ABCDEFGHIJKLMNOP"
    hook = "https://hooks.example.invalid/services/T000/B000/SECRETPART"
    log_run(conn, "leaky step", "ok", f"mail pat@example.com key {secret_key} hook {hook}")
    reject_id = create_draft(conn, 1, "first_week_plan", "d")
    reject(conn, reject_id, "Eli", "ask maya.chen@juniperlabs.example about it")
    html = page(conn)
    assert not EMAIL.search(html)
    for secret in (secret_key, "SECRETPART", "hooks.example.invalid"):
        assert secret not in html
    for (email,) in conn.execute("SELECT email FROM employees UNION SELECT manager_email FROM employees"):
        assert email not in html
    assert "draft text" not in html  # draft bodies are never shown


def test_page_is_escaped_and_has_no_script(tmp_path):
    conn = loaded(tmp_path)
    log_run(conn, "<script>alert(1)</script>", "ok", "<b>bold</b>")
    html = page(conn)
    assert "<script" not in html.lower() and "&lt;script&gt;" in html


def test_dashboard_module_cannot_call_any_api():
    # It must not import the Claude client, requests, slack or plan code.
    tree = ast.parse(Path(dashboard.__file__).read_text())
    imported = {n.module if isinstance(n, ast.ImportFrom) else a.name
                for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in (n.names if isinstance(n, ast.Import) else [n])}
    assert not imported & {"requests", "anthropic", "urllib", "http"}
    assert "slack" not in imported and "plan" not in imported


def test_cli_writes_the_page_and_a_second_run_is_identical(tmp_path):
    db, out = str(tmp_path / "t.db"), tmp_path / "docs" / "index.html"
    loaded(tmp_path).close()
    assert main(["dashboard", "--db", db, "--out", str(out), "--today", TODAY]) == 0
    first = out.read_text()
    assert main(["dashboard", "--db", db, "--out", str(out), "--today", TODAY]) == 0
    assert out.read_text() == first  # no churn, so no pointless commits
