"""Safety net for the whole test suite: no test can ever reach Slack or Claude.

Every test starts with no webhook and no API key set, and any real HTTP post raises. A test that
wants to check Slack behaviour sets a fake webhook and replaces slack.requests.post
with a recorder (see tests/test_slack.py)."""
import pytest
import requests

from onboarding_agent import plan, slack


@pytest.fixture(autouse=True)
def never_call_slack(monkeypatch):
    monkeypatch.delenv(slack.WEBHOOK_VAR, raising=False)
    monkeypatch.delenv(plan.KEY_VAR, raising=False)

    def boom(*args, **kwargs):
        raise AssertionError("a test tried to make a real HTTP request (Slack must never be called)")

    monkeypatch.setattr(requests, "post", boom)
    monkeypatch.setattr(requests.Session, "request", boom)
    monkeypatch.setattr(plan, "_make_client", boom)  # a test can pass its own fake client instead
