# Onboarding Agent (public repo)

Read BUILD_PLAN.md first; it's the source of truth for scope. Public portfolio project: never mention job searching, applications, or resumes, and never commit secrets (API keys live in a local .env or GitHub Actions secrets).

## Rules for the agent itself
- Juniper Labs and every person and event here are fictional. Never use a real company's employee data.
- Nothing is sent to a new hire or their manager without a person approving it first. The approval step is enforced in code, never only in a prompt.
- Dates, counts, and "overdue" are computed in code (Python or SQL), never by the model.
- Every run is logged (what happened, what failed). A failed step alerts someone instead of failing silently.
- At most 3 Claude calls per new hire.
- Before any command that needs approval, say in one plain sentence what it does and whether it changes, deletes, or sends anything outside this machine.
- Nash builds this himself with Claude Code. Explain choices as you go; don't silently write large pieces he hasn't seen.

## Git commits
- Always commit as the author Nash Mahler <mahler.nash@gmail.com>.
- Never set the commit author to Claude or noreply@anthropic.com, and don't add Claude attribution lines.
