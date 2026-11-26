# Onboarding Agent

When a new hire accepts their offer, this agent starts onboarding right away: it creates the checklist with owners and due dates, drafts a first-week plan that the manager approves, posts a welcome in Slack, and flags anything overdue.

> Juniper Labs and everyone in `data/` are fictional. No real employee data.

## The rules it follows

- **A person approves anything sent to a person.** Enforced in code.
- **Dates and counts are computed in code**, never by the model.
- **Every run is logged, and failures alert someone.**
- **At most 3 Claude calls per new hire.**

## How to run

```bash
pip install -r requirements.txt
python -m pytest
python -m onboarding_agent load data/sample_events
```

### Draft, approve, send

```bash
python -m onboarding_agent draft cand_1001
python -m onboarding_agent approve 1 --by "Eli Moss"      # or: reject 1 --by "Eli Moss" --reason "..."
python -m onboarding_agent send 1
```

`draft` writes a first-week plan and saves it as `pending`; nothing is sent. Only `approve` (by a named person) lets `send` deliver it, and `send` refuses anything that is pending, rejected or already sent. The plan comes from one Claude call using the key in `ONBOARDING_API_KEY` (set it in a local `.env` or your shell; never commit it). Without a key, a clearly labeled sample plan is saved instead. Tests never call the real API. Delivery goes to Slack, or prints to the console if no webhook is set.

Safety guards: a database trigger refuses to set any row to `sent` unless it was `approved`, even for a direct edit with the `sqlite3` tool. After a rejection, `draft` makes a fresh draft. Each hire gets at most 3 Claude calls, counted from `runs_log` in code; a 4th is refused before any request is made. See a real result in [examples/first_week_plan_maya.md](examples/first_week_plan_maya.md).

`load` reads every offer-accepted event in the folder, adds the new hire, and creates their onboarding tasks in a local SQLite file (`onboarding.db`, or pick one with `--db`). Running it again creates no duplicates. It prints one line per event, writes each result to `runs_log`, and exits with code 1 if any event failed (the sample folder includes one bad event on purpose).

## Slack

Set `ONBOARDING_SLACK_WEBHOOK` (an incoming-webhook URL) in your shell or a local `.env`; never commit it. Without it, every message prints to the console instead, so nothing here needs Slack to run. Tests never call Slack: a global test fixture removes the webhook and makes any real HTTP request raise.

What gets posted:

| When | Message |
|---|---|
| A draft is saved | "Plan pending approval #N" with the hire, manager and the draft, labeled as not yet sent |
| `send` / `approve --send` on an approved draft | "Welcome to Juniper Labs, <name>" with the approved plan and the approver's name |
| Any step is logged as `failed` | "Step failed: <step>" with the reason. The `runs_log` row is written first |
| `reject` | "Plan #N rejected by NAME: REASON" |
| `overdue --post` | The overdue report |

If an alert itself can't be delivered, that is printed and written to `runs_log` as a failed `slack alert` row, never dropped.

## Overdue report

```bash
python -m onboarding_agent overdue          # print it
python -m onboarding_agent overdue --post   # also post it to Slack
python -m onboarding_agent overdue --today 2026-11-26   # pretend it is this day
```

The counting is SQL ([queries/overdue_by_owner.sql](queries/overdue_by_owner.sql) and [queries/overdue_tasks.sql](queries/overdue_tasks.sql)). Python picks "today" and passes it in. A task is overdue when it is open and its due date is before today.

## Run it on GitHub (Actions buttons)

Add two repo secrets (Settings > Secrets and variables > Actions): `ONBOARDING_API_KEY` and `ONBOARDING_SLACK_WEBHOOK`. Then, under the Actions tab:

1. **Run onboarding**: loads `data/sample_events` and drafts a plan per hire (each posts "pending approval" to Slack). `cand_1005` is the planted failure: it is missing a start date, so it logs a failed row and posts an alert. The run is green when every failure was logged and alerted; it goes red only for something unexpected (a crash, or an alert that could not be delivered).
2. **Approve**: inputs are the approval id (from the Slack message) and your name. It approves and sends the welcome to Slack. The name is typed by whoever clicks, so the real control is who has write access to the repo.
3. **Reject**: inputs are the approval id, your name and a reason. It rejects a pending draft, saves the reason, and posts "Plan #N rejected by NAME: REASON" to Slack. The next **Run onboarding** drafts a fresh plan for that hire (still within the 3-Claude-calls-per-hire cap; a 4th draft is refused, logged and alerted).
4. **Overdue report**: posts the report to Slack.

**Where the database lives between runs:** a runner starts empty every time, so the SQLite file is committed to the repo at `data/demo/onboarding_demo.db`. Each workflow saves it back to `main` as `github-actions[bot]`, and the next run starts from it. Everything in it is fictional. The three buttons share one concurrency group so two runs can't overwrite each other. If an approved plan fails to send (for example Slack is down), it stays `approved`; run `python -m onboarding_agent send <id>` against the pulled database to retry.

## Status

Week 4 of my weekly builds, in progress. See [BUILD_PLAN.md](BUILD_PLAN.md).

More builds at [nashmahler.github.io/builds](https://nashmahler.github.io/builds).
