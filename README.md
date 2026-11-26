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
python -m onboarding_agent approve 1 --by "Eli Moss"
python -m onboarding_agent send 1
```

`draft` writes a first-week plan and saves it as `pending`; nothing is sent. Only `approve` (by a named person) lets `send` deliver it, and `send` refuses anything that is pending, rejected or already sent. The plan comes from one Claude call using the key in `ONBOARDING_API_KEY` (set it in a local `.env` or your shell; never commit it). Without a key, a clearly labeled sample plan is saved instead. Tests never call the real API. Delivery prints to the console until Slack is added.

Safety guards: a database trigger refuses to set any row to `sent` unless it was `approved`, even for a direct edit with the `sqlite3` tool. After a rejection, `draft` makes a fresh draft. Each hire gets at most 3 Claude calls, counted from `runs_log` in code; a 4th is refused before any request is made. See a real result in [examples/first_week_plan_maya.md](examples/first_week_plan_maya.md).

`load` reads every offer-accepted event in the folder, adds the new hire, and creates their onboarding tasks in a local SQLite file (`onboarding.db`, or pick one with `--db`). Running it again creates no duplicates. It prints one line per event, writes each result to `runs_log`, and exits with code 1 if any event failed (the sample folder includes one bad event on purpose).

## Status

Week 4 of my weekly builds, in progress. See [BUILD_PLAN.md](BUILD_PLAN.md).

More builds at [nashmahler.github.io/builds](https://nashmahler.github.io/builds).
