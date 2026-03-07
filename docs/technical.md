# Technical Guide

## Purpose
`obsidian-knowledge-ingestor` is a local-first learning project for building a source-to-vault pipeline:
- collect content from Zhihu and WeChat
- normalize it into a stable Markdown note format
- store it in an Obsidian vault
- let agents query only the vault through the official Obsidian CLI

The project is intentionally practical. It favors stable boundaries and observable behavior over crawler cleverness.

## Technology Stack
- Runtime: Python 3
- Packaging: `pyproject.toml`
- Browser automation: Playwright
- HTML parsing and normalization: BeautifulSoup plus in-repo HTML utilities
- Storage model: Markdown notes plus YAML frontmatter in an Obsidian vault
- State tracking: JSON state files under `Sources/_state`

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
  - `verification.py`: source-vs-vault verification logic
- `docs/`: architecture, plan, and technical docs
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

Important constraint:
- local WeChat cache is no longer treated as a history-discovery source
- it is used only to recover seed URLs with `key`, `pass_ticket`, and related query parameters when the client has already opened an article
- the actual article history list comes from `profile_ext/getmsg`, not from cached article URLs

This means the project can now recover real history for accounts that expose a usable history feed from a reachable seed article, but it still does not claim universal full-history extraction for every public account.

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
Current CLI commands:
- `oki auth <source>`
- `oki ingest <source> --target <file>`
- `oki verify zhihu --target <file> --vault <path>`
- `oki search <query>`
- `oki read <note-path>`
- `oki ask <prompt>`

## Testing
Current automated coverage focuses on:
- normalization
- vault writing
- incremental skip behavior
- WeChat verification-wall detection
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
