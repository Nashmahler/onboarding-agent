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

`load` reads every offer-accepted event in the folder, adds the new hire, and creates their onboarding tasks in a local SQLite file (`onboarding.db`, or pick one with `--db`). Running it again creates no duplicates. It prints one line per event, writes each result to `runs_log`, and exits with code 1 if any event failed (the sample folder includes one bad event on purpose).

## Status

Week 4 of my weekly builds, in progress. See [BUILD_PLAN.md](BUILD_PLAN.md).

More builds at [nashmahler.github.io/builds](https://nashmahler.github.io/builds).
