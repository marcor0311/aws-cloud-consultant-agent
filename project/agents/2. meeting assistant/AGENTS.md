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
approved input files: meeting summary PDF, project brief PDF, presentation HTML/PDF
and full transcript PDF, with their revision manifest. Preserve earlier three-file
and four/five/six-file contracts, including approved speaker-notes.md when present.
Reconcile remote repository, commit and issue state
before retries; never force an existing branch or overwrite human changes.

Run offline tests in `backend/tests/project_opening/`. PostgreSQL tests require
an isolated `WORKFLOW_TEST_POSTGRES_URL`. Never use active business databases for
tests. The guided MCP flow does not use model inference. Separate legacy drafting
commands require explicit per-execution authorization; keep any OAuth credentials
private and never fall back to an API key.

The board's decision is made outside the agent. Guide Stuart through MCP in
this order: select a prepared project, record a yes/no decision, and, if yes,
collect queue position, approved budget and architect. Summarize every value and
the planned repository, publication of the exact approved files and architecture issue, then wait
for Stuart's final confirmation before any GitHub write. Verify the architect with a
read-only GitHub lookup before the summary. Invalid answers repeat the question
with an `error`. A rejection is confirmed, then recorded once without creating a
repository or issue; the project leaves the prepared list and cannot be approved
later. Do not simulate votes or create board minutes for this workflow.

Record Lead Time for Direction in the `stage-2` phase, from Agent 1's handoff to
the recorded decision, and the GitHub opening in `project-opening`. Expose them
through `consultar_metricas_apertura`; never infer unrecorded time.

Persist the MCP conversation in the PostgreSQL LangGraph checkpointer so it can
resume after restart. Persist the exact approved bytes of all approved Agent 1 inputs
and the manifest in PostgreSQL before GitHub publication. Verify hashes at
publication and reconcile remote state before retries.
