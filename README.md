# Onboarding Agent

When a new hire accepts their offer, this agent starts onboarding right away: it creates the checklist with owners and due dates, drafts a first-week plan that the manager approves, posts a welcome in Slack, and flags anything overdue.

> Juniper Labs and everyone in `data/` are fictional. No real employee data.

## The rules it follows

- **A person approves anything sent to a person.** Enforced in code.
- **Dates and counts are computed in code**, never by the model.
- **Every run is logged, and failures alert someone.**
- **At most 3 Claude calls per new hire.**

## Status

Week 4 of my weekly builds, in progress. See [BUILD_PLAN.md](BUILD_PLAN.md).

More builds at [nashmahler.github.io/builds](https://nashmahler.github.io/builds).
