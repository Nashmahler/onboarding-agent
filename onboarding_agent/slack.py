"""Slack delivery through one incoming webhook, with a console fallback.

The webhook URL is a secret: it is read from ONBOARDING_SLACK_WEBHOOK, and it is
never printed, logged or put in an error message. Without it, every message is
printed to the console instead, so the whole project still runs with no Slack.
"""
import os
import sqlite3
import sys
from datetime import datetime, timezone

import requests

WEBHOOK_VAR = "ONBOARDING_SLACK_WEBHOOK"
TIMEOUT_SECONDS = 10
ALERT_FAILED_STEP = "slack alert"  # runs_log step used when an alert itself could not be delivered


class SlackError(Exception):
    """A message could not be delivered. The text never contains the webhook URL."""


def escape(text: str) -> str:
    """Slack treats & < > as markup, so escape them in anything we did not write."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def post(text: str, *, stream=None) -> bool:
    """Send one message. Return True if it went to Slack, False if it was printed instead."""
    url = os.environ.get(WEBHOOK_VAR, "").strip()
    if not url:
        print(f"[console, no {WEBHOOK_VAR}]\n{text}", file=stream or sys.stdout)
        return False
    try:
        response = requests.post(url, json={"text": text}, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        # Only the exception's class name: its text can include the URL.
        raise SlackError(f"Slack post failed ({type(exc).__name__})") from None
    if not response.ok:
        raise SlackError(f"Slack post failed (HTTP {response.status_code})")
    return True


def alert(conn: sqlite3.Connection, step: str, detail: str) -> bool:
    """Tell someone a step failed. Never raises (it runs inside the failure path).

    Return True if the alert reached Slack or the console. If Slack itself is down, say so
    on stderr AND write a 'slack alert' failed row to runs_log, so it can't pass unnoticed."""
    try:
        post(f":rotating_light: *Step failed:* `{escape(step)}`\n{escape(detail)}", stream=sys.stderr)
        return True
    except SlackError as exc:
        print(f"warning: could not deliver the alert for {step!r}: {exc}", file=sys.stderr)
        # A raw insert, not log_run: log_run would try to alert again and loop.
        with conn:
            conn.execute(
                "INSERT INTO runs_log (ran_at, step, status, detail) VALUES (?, ?, 'failed', ?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), ALERT_FAILED_STEP,
                 f"alert for {step!r} not delivered: {exc}"),
            )
        return False


def pending_message(approval_id: int, employee: sqlite3.Row, draft: str) -> str:
    return (
        f":hourglass_flowing_sand: *Plan pending approval #{approval_id}* for "
        f"{escape(employee['name'])} ({escape(employee['title'])}), manager {escape(employee['manager_name'])}.\n"
        f"Nothing has been sent to the new hire. To release it, run the *Approve* workflow "
        f"with approval id *{approval_id}* and your name.\n"
        f"--- DRAFT ---\n{escape(draft)}"
    )


def welcome_message(approval: sqlite3.Row, employee: sqlite3.Row) -> str:
    return (
        f":tada: *Welcome to Juniper Labs, {escape(employee['name'])}!*\n"
        f"To: {escape(employee['email'])}, cc manager {escape(employee['manager_name'])} "
        f"({escape(employee['manager_email'])})\n"
        f"_Plan #{approval['id']} approved by {escape(approval['decided_by'] or 'unknown')}_\n\n"
        f"{escape(approval['draft'])}"
    )


def slack_sender(approval: sqlite3.Row, employee: sqlite3.Row) -> None:
    """The sender for send_approved(): post the welcome and approved plan.
    send_approved has already checked the approval; this only delivers."""
    post(welcome_message(approval, employee))
