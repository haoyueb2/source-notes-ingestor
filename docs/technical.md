# Technical Guide

## Purpose
`obsidian-knowledge-ingestor` is a local-first ingestion project:
- collect content from Zhihu and WeChat
- normalize it into a stable Markdown note format
- store it in an Obsidian vault

The repository intentionally no longer ships a built-in QA runtime. Vault retrieval and synthesis now live in the repo-local Obsidian QA plugin and skill.

## Technology Stack
- Runtime: Python 3
- Packaging: `pyproject.toml`
- Browser automation: Playwright
- HTML parsing and normalization: BeautifulSoup plus in-repo HTML helpers
- Storage model: Markdown notes plus YAML frontmatter in an Obsidian vault
- State tracking: JSON state files under `Sources/_state`
- Agent QA path: repo-local plugin/skill plus the official Obsidian CLI

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
  - `verification.py`: source-vs-vault verification logic
- `plugins/obsidian-qa/`: model-agnostic Obsidian QA plugin and skill
- `docs/`: architecture, plan, and technical docs
- `samples/`: example target files
- `targets/`: local real-world target configs
- `tests/`: ingestion-focused unit tests

## Data Flow
```text
Zhihu / WeChat
  -> adapter fetch_source()
  -> RawItem
  -> normalize()
  -> CanonicalNote
  -> write_note()
  -> Obsidian Vault
  -> Obsidian QA plugin/skill
  -> official Obsidian CLI
  -> agent answer from raw notes
```

## Core Contracts
The project keeps these ingestion interfaces stable:
- `fetch_source(target, auth_ctx, since) -> raw_items[]`
- `normalize(raw_item) -> canonical_note`
- `write_note(canonical_note, vault_path) -> note_path`

The Python package does not define a QA contract anymore. Retrieval is delegated to the plugin/skill layer.

## Zhihu Implementation
Zhihu supports three acquisition modes:
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
Zhihu pages can expose unrelated answers or pins through recommendations or interaction surfaces. The adapter verifies author identity before materializing items into the vault.

### Post-ingest verification
Zhihu verification uses three count layers:
- `profile_counts`: counts shown in the profile header
- `accessible_counts`: counts actually exposed through accessible lists
- `vault_counts`: counts written into the vault

This keeps source-visible drift separate from pipeline correctness.

## WeChat Implementation
WeChat supports:
- seed article ingestion
- browser-session page fetch
- `discover wechat`, which derives `mp/profile_ext?action=getmsg` from a reachable seed article and paginates through history
- streaming note materialization while the browser queue is still being consumed
- verification-aware resume based on vault state

Important constraint:
- local WeChat cache is not treated as authoritative history discovery
- it is used only to recover seed URLs with `key`, `pass_ticket`, and related query parameters
- the actual history list comes from `profile_ext/getmsg`

### Detailed WeChat route
Phase 1: history discovery
1. Start from one or more reachable article URLs.
2. Recover the full article URL when possible, including `__biz`, `uin`, `key`, and `pass_ticket`.
3. Fetch the article HTML and extract `appmsg_token`.
4. Call `mp/profile_ext?action=getmsg` with those parameters.
5. Parse `general_msg_list` into a flat URL queue.

Phase 2: body ingestion
1. Feed the discovered article URLs into the browser-backed WeChat adapter.
2. Generate a stable `content_id` from `mid + idx + sn` for query-style article URLs.
3. Normalize each article immediately after fetch.
4. Write Markdown and state immediately, instead of waiting for the full queue to finish.

### Verification-aware resume
When WeChat serves a verification page mid-run:
1. the current note is not written
2. previously written notes remain durable
3. state already contains completed `content_id`s
4. the CLI recomputes the remaining URL queue from the original target and current state
5. ingestion retries from the remaining URLs

## Obsidian Storage Model
Vault layout:
- `Sources/Zhihu/<author>/answers/*.md`
- `Sources/Zhihu/<author>/thoughts/*.md`
- `Sources/Zhihu/<author>/articles/*.md`
- `Sources/WeChat/<account>/*.md`
- `Sources/_assets/...`
- `Sources/_state/...`

Each note includes:
- YAML frontmatter for metadata and provenance
- normalized Markdown body
- archived raw HTML path when available
- checksum-based update semantics

## CLI Surface
`oki` is ingestion-only:
- `oki auth <source>`
- `oki ingest <source> --target <file>`
- `oki discover wechat --target <file>`
- `oki verify zhihu --target <file> --vault <path>`

Anything that queries the vault should now go through the repo-local Obsidian QA plugin/skill.

## Obsidian QA Plugin
The plugin is intentionally thin:
- it does not maintain a parallel note index
- it does not generate scope maps or derived context packs
- it does not persist ask sessions or usage logs

Instead, it gives the agent a strict retrieval workflow:
1. refine the question
2. run multiple short `obsidian search` queries
3. open matched raw notes with `obsidian read`
4. answer only from the raw note evidence

This keeps the vault as the single source of truth while removing the duplicated QA product layer from `oki`.
