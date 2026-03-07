# Delivery Plan

## v0 scaffolding
- Initialize repository layout, core documentation, and environment placeholders.
- Freeze architecture boundaries, interfaces, vault layout, and source strategy.
- Keep the repository implementation-free so runtime choices can be made later without reworking the contract.

Exit criteria:
- Repository structure exists.
- README and architecture docs are sufficient for a new implementer.
- Initial git history contains the scaffold-only baseline.

## v1 ingestion
- Choose implementation stack and runtime conventions.
- Build `zhihu_adapter` with public-entry and logged-in collection paths.
- Build `wechat_adapter` with primary RSS-style ingestion plus backfill path.
- Implement normalization into the canonical note model.
- Implement vault writing, asset download handling, and state persistence.
- Support first-run full sync and repeat incremental sync.

Exit criteria:
- A target Zhihu author yields answers, thoughts, and articles in the vault.
- A target WeChat account yields historical articles and repeatable incremental updates.
- Duplicate runs do not create duplicate notes.

## v2 qa
- Add the `qa_runner` wrapper around the official Obsidian CLI.
- Define standard retrieval flows: search, open note, scoped recall for a target author/account/topic.
- Validate that Claude/Codex can answer against vault content without touching raw crawler outputs.

Exit criteria:
- Vault notes are searchable through the official CLI.
- Agent workflows can answer source-specific questions using retrieved notes.
- Query behavior is documented with example prompts and expected outputs.

## v3 ops
- Add scheduling, structured logging, retry handling, and failure reporting.
- Harden auth/session refresh workflows.
- Add backup and recovery guidance for state and vault writes.
- Optionally add local containerization once runtime choices are fixed.

Exit criteria:
- Scheduled syncs are stable on a local machine.
- Login/session expiry produces actionable recovery messages.
- State and note write failures are observable and recoverable.

## Cross-Phase Acceptance Rules
- The vault remains the single agent-facing source of truth.
- Source-specific anti-bot handling stays isolated in adapters.
- No phase should introduce direct agent dependency on crawler internals.
- Scope exclusions remain unchanged unless explicitly revised.
