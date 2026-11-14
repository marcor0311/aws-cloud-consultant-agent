# Meeting Assistant

Agent 2 opens approved consulting projects. Its entry point is `src/agent.py`;
its domain, application service and LangGraph live in `backend/app/project_opening/`.
Do not import this numbered folder as a Python package or duplicate backend rules.

Use the existing workflow PostgreSQL database and PostgreSQL checkpointer. Queue
positions, per-company project numbers, approvals, budget, architect and direction
comments belong to that database. The issue contains the architecture assignment,
including its budget context, rather than internal prioritization comments.

Every template follows the same naming rule:
`AWS Cloud Consulting Project <Company> <NN> <Project>`, with its lowercase,
accent-free, hyphen-separated repository name. Reserve numbers in PostgreSQL.

Use `templates/architecture.md` as the sole issue-body contract. Publish the exact
approved input files, including the presentation in HTML and PDF and approved speaker-notes.md.
New deliveries require six files and their revision manifest; persisted four/five-file records remain unchanged.
Reconcile remote repository, commit and issue state
before retries; never force an existing branch or overwrite human changes.

Run offline tests in `backend/tests/project_opening/`. PostgreSQL tests require
an isolated `WORKFLOW_TEST_POSTGRES_URL`. Never use active business databases for
tests. Never automatically run real inference: each execution needs explicit
authorization through `draft --allow-inference` or the explicit `agent2-live`
command. Use ChatGPT OAuth with renewal
and logout; keep credentials private and never fall back to an API key.

Require a unanimous board certificate before opening. Real votes only enter
through signed Slack callbacks for the configured workspace, app, channel and
message. Never expose a manual MCP tool that casts votes for board members.
Generate immutable minutes and JSON evidence in `docs/02-board/`, bound to the
exact input hashes and budget. Simulated votes normally only authorize preview runs.
The user explicitly authorized an exception for this fictitious Nike case:
`make agent2-live MOCK_BOARD=1` may publish to real GitHub with mock Slack votes.
Keep those votes and minutes marked as simulated, record the activation in
PostgreSQL, and scope the exception to the specified fictitious case and execution.
Never replace a real ballot, fabricate real votes, or enable this by default.
