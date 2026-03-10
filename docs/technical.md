# Technical Guide

## Purpose
`obsidian-knowledge-ingestor` is a local-first learning project for building a source-to-vault pipeline:
- collect content from Zhihu and WeChat
- normalize it into a stable Markdown note format
- store it in an Obsidian vault
- let agents query only the vault through the official Obsidian CLI

The project is intentionally practical. It favors stable boundaries and observable behavior over crawler cleverness.

It is also a learning project. The docs are intentionally somewhat more detailed than a minimal runbook, because part of the value of this repository is understanding why specific boundaries and tradeoffs exist.

Suggested reading order for learning:
1. Read `README.md` for the end-to-end workflow.
2. Read this guide for implementation tradeoffs and runtime boundaries.
3. Inspect `src/obsidian_knowledge_ingestor/` module by module.
4. Use `tests/` to see which behaviors are treated as contracts.

## Technology Stack
- Runtime: Python 3
- Packaging: `pyproject.toml`
- Browser automation: Playwright
- HTML parsing and normalization: BeautifulSoup plus in-repo HTML utilities
- Storage model: Markdown notes plus YAML frontmatter in an Obsidian vault
- State tracking: JSON state files under `Sources/_state`
- QA execution: local `codex` plus the official Obsidian CLI plus scope-derived packs

## Repository Structure
- `src/obsidian_knowledge_ingestor/`
  - `adapters/`
    - `zhihu.py`: Zhihu acquisition logic
    - `wechat.py`: WeChat acquisition logic
    - `feed.py`: shared feed/manual seed helpers
  - `browser_automation.py`: browser session persistence and page discovery
  - `normalizer.py`: canonical note mapping
  - `vault_writer.py`: note materialization, assets, and sync state
  - `pipeline.py`: end-to-end ingestion orchestration
  - `qa_runner.py`: official Obsidian CLI wrapper
  - `qa_builder.py`: scope-derived QA pack generation
  - `scope_loader.py`: person-level scope loading
  - `verification.py`: source-vs-vault verification logic
- `docs/`: architecture, plan, and technical docs
- `scopes/`: person-level scope definitions
- `samples/`: example target files
- `targets/`: local real-world target configs
- `tests/`: unit tests

## Data Flow
```text
Zhihu / WeChat
  -> adapter fetch_source()
  -> RawItem
  -> normalize()
  -> CanonicalNote
  -> write_note()
  -> Obsidian Vault
  -> build-qa(scope)
  -> Derived/Scopes/<scope_id>/*.md
  -> query_vault()
```

## Core Contracts
The project keeps four logical interfaces stable:
- `fetch_source(target, auth_ctx, since) -> raw_items[]`
- `normalize(raw_item) -> canonical_note`
- `write_note(canonical_note, vault_path) -> note_path`
- `query_vault(prompt, scope) -> results`

These are the project’s actual architecture boundary. Everything else can change behind them.

## Zhihu Implementation
Zhihu currently supports three acquisition modes:
- browser-discovered page ingestion
- authenticated API-backed ingestion
- manual seed ingestion from URLs or saved HTML

### Why API plus browser
Pure HTTP requests are fragile on Zhihu. The working path is:
1. persist a real logged-in browser session with `oki auth zhihu`
2. reuse that session for acquisition
3. prefer API-backed extraction when the session can access the data
4. fall back to page discovery and page fetch when needed

### Author filtering
Zhihu pages can expose unrelated answers or pins through recommendations or interaction surfaces. The adapter now verifies author identity before materializing items into the vault.

### Post-ingest verification
Zhihu verification uses three count layers:
- `profile_counts`: counts shown in the profile header
- `accessible_counts`: counts actually exposed through accessible lists or authenticated session-backed surfaces
- `vault_counts`: counts written into the vault

This is deliberate. For the target `lin-lin-98-23`, the system currently observes:
- profile: `27 answers / 3 articles / 60 thoughts`
- accessible: `26 answers / 3 articles / 60 thoughts`
- vault: `26 answers / 3 articles / 60 thoughts`

This means the pipeline is internally consistent for accessible content, while Zhihu still exposes a one-answer discrepancy between profile summary and accessible answer list.

## WeChat Implementation
WeChat currently supports:
- seed article ingestion
- browser-session page fetch
- `discover wechat`, which derives `mp/profile_ext?action=getmsg` from a reachable seed article and paginates through history
- streaming note materialization while the browser queue is still being consumed
- verification-aware resume based on vault state

Important constraint:
- local WeChat cache is no longer treated as a history-discovery source
- it is used only to recover seed URLs with `key`, `pass_ticket`, and related query parameters when the client has already opened an article
- the actual article history list comes from `profile_ext/getmsg`, not from cached article URLs

This means the project can now recover real history for accounts that expose a usable history feed from a reachable seed article, but it still does not claim universal full-history extraction for every public account.

### Detailed WeChat route
The working route is intentionally split into two phases.

Phase 1: history discovery
1. Start from one or more reachable article URLs.
2. Recover the full article URL when possible, including `__biz`, `uin`, `key`, and `pass_ticket`.
3. Fetch the article HTML and extract `appmsg_token`.
4. Call `mp/profile_ext?action=getmsg` with those parameters.
5. Parse `general_msg_list` and expand single-article plus multi-article entries into a flat URL queue.

Phase 2: body ingestion
1. Feed the discovered article URLs into the browser-backed WeChat adapter.
2. Generate a stable `content_id` from `mid + idx + sn` for query-style article URLs.
3. Normalize each article immediately after fetch.
4. Write Markdown and state immediately, instead of waiting for the full queue to finish.

Why this split matters:
- discovery and ingestion fail for different reasons
- history discovery can be validated by queue length
- body ingestion can resume from `Sources/_state` even if WeChat interrupts the session

### Verification-aware resume
When WeChat serves a verification page mid-run:
1. the current note is not written
2. all previously written notes remain durable in the vault
3. state already contains the completed `content_id`s
4. the CLI recomputes the remaining URL queue from the original target and current state
5. ingestion retries from the remaining URLs

This is not captcha solving. It is failure recovery around a human-verification boundary.

## Obsidian Storage Model
Vault layout:
- `Sources/Zhihu/<author>/answers/*.md`
- `Sources/Zhihu/<author>/thoughts/*.md`
- `Sources/Zhihu/<author>/articles/*.md`
- `Sources/WeChat/<account>/*.md`
- `Derived/Scopes/<scope_id>/*.md`
- `Sources/_assets/...`
- `Sources/_state/...`

Each note includes:
- YAML frontmatter for metadata and provenance
- normalized Markdown body
- archived raw HTML path when available
- checksum-based update semantics

## CLI Surface
Current CLI commands:
- `oki auth <source>`
- `oki ingest <source> --target <file>`
- `oki discover wechat --target <file>`
- `oki verify zhihu --target <file> --vault <path>`
- `oki search <query>`
- `oki read <note-path>`
- `oki build-qa --scope <scope_id>`
- `oki qa-search --scope <scope_id> --query <text>`
- `oki qa-read --path <note-path>`
- `oki qa-open-derived --scope <scope_id> --kind <kind>`
- `oki ask <prompt> --scope <scope_id>`

For this local repository setup, the CLI now also assumes a few defaults to reduce repetitive typing:
- default scope: `linlin`
- default `oki ask` context mode: `map`
- default vault: `/Users/haoyuebai/Documents/oki-main-vault`, unless `OBSIDIAN_VAULT_PATH` is explicitly set

That means many common local commands can now be shortened to:
- `python3 -m obsidian_knowledge_ingestor.cli build-qa --rebuild`
- `python3 -m obsidian_knowledge_ingestor.cli ask '感到无聊老想出去玩social是对的吗'`

For other machines or vaults, explicit flags are still preferable so the local repo defaults do not leak into a different environment.

## QA Layer
The QA layer is agentic, but the live retrieval loop is no longer delegated blindly to Codex:
1. `oki build-qa` builds a person-level scope package.
2. The program generates deterministic files:
   - `manifest.md`
   - `corpus_index.md`
   - `full_context.md`
3. Local `codex` generates higher-level scope maps:
   - `overview.md`
   - `themes.md`
4. `oki ask` preloads the derived map for the requested scope.
5. Local `codex` first generates a structured retrieval plan:
   - `question_reframing`
   - `query_plan[]`
6. The program then executes the retrieval plan itself:
   - run multiple `search_scope(...)` calls
   - read raw notes through the official Obsidian CLI
   - aggregate and rank the evidence bundle
7. Local `codex` then writes the final answer from the raw evidence bundle only.
8. Final output must include:
   - a full analysis trace
   - the final answer
   - citations back to raw vault notes

Important boundary:
- derived notes are navigation aids and context packs, not final evidence
- final evidence must come from raw notes under `Sources/**`
- cross-source scope membership is explicit in `scopes/*.json`

### Why the ask flow changed
The earlier ask design relied on `codex exec` directly deciding when to invoke `qa-search`, `qa-read`, and `qa-open-derived`.

That was attractive in principle, but unstable in live use:
- tool calling inside `codex exec` was not reliable enough for repeated multi-step retrieval
- official Obsidian CLI invocations were more stable when executed directly by the program
- the final answers depended too much on whether Codex happened to search enough times

The current design keeps the best part of the agentic approach, namely:
- Codex interprets the user question
- Codex reframes the problem and proposes retrieval angles
- Codex synthesizes the final serious answer

But it moves the brittle part, namely repeated vault retrieval execution, back into deterministic Python code.

### Current ask execution model
`oki ask --scope <scope_id>` now follows this sequence:
1. verify that `Derived/Scopes/<scope_id>/` exists
2. preload `overview.md` and `themes.md`
3. preload either:
   - a compact `corpus_index.md` only as a fallback aid in `map` mode
   - `full_context.md` in `fulltext` mode
4. ask Codex for a structured retrieval plan in JSON
5. normalize and extend that plan with fallback queries derived from the user prompt
6. run scope-limited raw-note searches programmatically
7. read the highest-value raw notes
8. build a bounded evidence bundle
9. ask Codex to produce a long-form Markdown answer from that bundle

### Streaming behavior
The QA layer uses `OKI_CODEX_STREAM` to control Codex subprocess streaming.

Current behavior:
- `build-qa` streams Codex output by default
- `oki ask` streams the retrieval-planning phase
- `oki ask` also streams the final answer in normal terminal mode
- `oki ask` also prints deterministic progress logs such as:
  - `[oki ask] planning retrieval`
  - `[oki ask] searching <query>`
  - `[oki ask] synthesizing final answer`
- `oki ask --json` keeps final answer synthesis non-streamed so the JSON payload stays clean

### Context modes
`oki ask` currently supports two context modes.

`map` mode:
- preload `overview` and `themes`
- use them as author-map context
- derive multiple retrieval queries
- if the first retrieval pass is too thin, retry planning with a compact `corpus_index`
- fetch raw notes for final evidence

`fulltext` mode:
- preload `overview`, `themes`, and a truncated `full_context` extract
- gives Codex a broader whole-corpus view before retrieval
- materially increases prompt size and token cost

The default remains `map` because it is cheaper and was sufficient for the first successful long-form smoke tests.

### Runtime knobs
The QA layer currently honors:
- `OKI_CODEX_MODEL`
- `OKI_CODEX_REASONING_EFFORT`
- `OKI_CODEX_STREAM`

Typical serious-study setup:
- `OKI_CODEX_MODEL=gpt-5.4`
- `OKI_CODEX_REASONING_EFFORT=medium`
- `OKI_CODEX_STREAM=1`

### Measured usage from a live smoke test
A successful live run on the real vault asked:
- `感到无聊老想出去玩social是对的吗`

Execution mode:
- scope: `linlin`
- context mode: `map`
- model: `gpt-5.4`
- reasoning effort: `high`

Observed token usage:
- one measured successful run: `35,623` total tokens
- a later stabilized rerun exposed `28,930` planning tokens; that measurement was recorded before the current streamed-final-answer path was added
- those numbers were recorded before the lighter `map` planning change that removed default `corpus_index` preload

This project does not currently know the denominator for Codex's rolling 5-hour quota, so it cannot convert those run totals into a trustworthy percentage.

## Testing
Current automated coverage focuses on:
- normalization
- vault writing
- incremental skip behavior
- WeChat verification-wall detection
- WeChat `content_id` stability for query-style article URLs
- WeChat history discovery parsing
- Zhihu browser discovery
- Zhihu author filtering
- Zhihu verification check classification

Run tests:
```bash
cd /Users/haoyuebai/Dev/ai/obsidian-knowledge-ingestor
source .venv/bin/activate
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Current Limits
- No captcha solving
- No guaranteed fully unattended long-running auth refresh
- No guaranteed complete WeChat historical backfill for accounts that do not expose a usable `profile_ext/getmsg` path
- Zhihu answer totals can differ between profile summary and accessible answer list
- Verification is practical, not perfect: it proves vault consistency against accessible content

## Why This Project Is Useful
This repository is a good learning project because it touches:
- browser-backed scraping
- anti-fragile adapter design
- canonical content modeling
- Markdown knowledge-base generation
- vault-oriented agent retrieval
- source-vs-storage verification instead of blind crawling
