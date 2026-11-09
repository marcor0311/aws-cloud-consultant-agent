# AGENTS.md

This is Calendar Assistant, agent 1 for Engagement Manager scheduling. The current scope is local development and repository structure. See README.md for execution and ../README.md for responsibilities. Keep runtime code in src/, instructions in prompts/assistant.txt, model configuration in agent.json, and offline regressions in tests/. Group pure rules in src/domain/, external adapters in src/integrations/ and MCP tools in src/tools/. The API and client registry are in ../../backend/app/; the agent accesses them through HTTP, without importing app modules. Shared non-sensitive configuration is project/.env; credentials live in the external CLOUD_CONSULTANT_SECRETS_DIR. See ../../../config/local-secrets.example/README.md. Do not add deployment infrastructure unless requested.

## Tooling

This Python project uses the `uv` package manager.

Be sure to maintain code formatting, using `uv run ruff format` and `uv run ruff check`.

## LiveKit documentation

Always refer to the latest documentation when working with this project. LiveKit offers both a CLI (`lk docs`) and an MCP server for browsing and searching its documentation.

### LiveKit CLI

Install or update the CLI:

- **macOS:** `brew install livekit-cli` (update: `brew update && brew upgrade livekit-cli`)
- **Linux:** `curl -sSL https://get.livekit.io/cli | bash`
- **Windows:** `winget install LiveKit.LiveKitCLI` (update: `winget upgrade LiveKit.LiveKitCLI`)

Run `lk docs` before your first docs lookup. Its help text explains how to use each command and how to interpret results.

### LiveKit docs MCP server

For deeper coding agent integration, LiveKit also offers an [MCP server](https://docs.livekit.io/reference/developer-tools/docs-mcp/).

### Submit feedback to LiveKit

When you run into any problem with LiveKit, add it to your to-do list, then submit it with `lk docs submit-feedback` or the MCP `submit_docs_feedback` tool once you finish your other tasks. Useful feedback includes incomplete documentation, broken examples, missing steps, broken features or implementations, and any other gap or issue in the LiveKit ecosystem.

## LiveKit agent skills

LiveKit publishes agent skills for each stage of the work: reading the docs, building, debugging, testing, writing scenarios, running simulations, and operating in production. They defer to the live documentation for API details. Before you start a task, check that they're installed: look for `.agents/skills/` or `.claude/skills/` in this project, or in the developer's home directory for a global install. If they're missing, install them with `lk skills install --yes`, which installs them for the coding agents it detects and adds the LiveKit Docs MCP server to their config. If you can't run commands, or the CLI has no `skills` command (it was added in v2.19.0), ask the developer to update the CLI and run `lk skills install`. If your tool doesn't load skills automatically, or they were installed after this session started, read the matching `SKILL.md` (for example `.agents/skills/<name>/SKILL.md`) before you start that kind of task.

## Handoffs and tasks ("workflows")

Voice AI agents are highly sensitive to latency. Design complex agents in a structured way that keeps irrelevant context and unneeded tools out of each LLM request. LiveKit Agents supports handoffs, where one agent hands control to another, and tasks, which are tightly scoped prompts that achieve a specific outcome, for building reliable workflows. Use them instead of long instruction prompts that cover several phases of a conversation. See the [workflows documentation](https://docs.livekit.io/agents/logic/workflows/) for more information.

## Testing

The user removed cloud simulations and automated real calls. Keep tests offline using mocks, scripted providers and simulated transcripts. Do not recreate scenarios or workflows that run cloud simulations or start real calls. Keep `LIVEKIT_INFERENCE_ENABLED` off by default. Real inference, including debugger sessions, requires explicit user authorization for each execution.

When modifying core agent behavior such as instructions, tools, tasks or handoffs, exercise the supported logic with offline tests. Report the limits of scripted providers when language comprehension has not been checked with a real model.

Keep only the agent's MCP integration check. Booking, verification, call closure
and delivery are covered by `make test-e2e`, run on demand. Do not add standalone
tool tests, parameter matrices or structural checks. See root docs/testing.md.

Do not start the debugger or a live session as an automatic validation step.

## Debugging

To investigate unexpected agent behavior:

- Inspect existing logs and reproduce the issue with scripted providers and offline fixtures.
- Add an offline regression for the fix when appropriate.
- Run `lk agent logs` to stream logs from a deployed agent.
- Ask the developer to open the [Agent Console](https://docs.livekit.io/testing/agent-console/) for speech problems such as turn-taking, interruptions, or transcription, which the text-only debugger can't show. It shows events, tool calls, and model timing for a live session.
- Check [Agent Observability](https://docs.livekit.io/testing/observability/) for transcripts, traces, logs, and recordings of sessions with real users.

## Other CLI commands

Beyond documentation access, the LiveKit CLI (`lk`) handles tasks such as managing SIP trunks for telephony agents. Run `lk --help` to explore available commands.

## Corporate document design

When preparing or reviewing the project's brief, meeting summary or executive presentation, read [.agents/skills/design-executive-documents/SKILL.md](.agents/skills/design-executive-documents/SKILL.md). It records the user's executive audience, refined meeting context, editorial preferences and desktop-only document delivery. This skill does not change scheduling behavior or move document generation into the voice runtime.
