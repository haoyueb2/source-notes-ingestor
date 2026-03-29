# Technical Guide

## Purpose
`source-notes-ingestor` is a local-first ingestion project:
- collect content from Zhihu and WeChat
- normalize it into a stable Markdown note format
- store it in a local notes library

The repository deliberately avoids shipping an in-process Q&A runtime. Retrieval is handled by a thin repo-local skill/plugin that uses `rg` and direct file reads.

## Technology Stack
- Runtime: Python 3
- Packaging: `pyproject.toml`
- Browser automation: Playwright
- HTML parsing and normalization: BeautifulSoup plus in-repo HTML helpers
- Storage model: Markdown notes plus YAML frontmatter in a local notes library
- State tracking: JSON state files under `Sources/_state`
- Agent retrieval path: repo-local plugin/skill plus shell tools such as `rg`

## Repository Structure
- `src/source_notes_ingestor/`
  - `adapters/`: Zhihu and WeChat acquisition logic
  - `browser_automation.py`: browser session persistence and page discovery
  - `normalizer.py`: canonical note mapping
  - `library_writer.py`: note materialization, assets, and sync state
  - `pipeline.py`: end-to-end ingestion orchestration
  - `verification.py`: source-vs-library verification logic
- `plugins/notes-rg-qa/`: model-agnostic retrieval skill/plugin
- `docs/`: architecture and technical docs
- `tests/`: ingestion-focused unit tests

## Data Flow
```text
Zhihu / WeChat
  -> adapter fetch_source()
  -> RawItem
  -> normalize()
  -> CanonicalNote
  -> write_note()
  -> local notes library
  -> notes-rg-qa skill/plugin
  -> rg + raw note reads
  -> agent answer from evidence
```

## Core Contracts
- `fetch_source(target, auth_ctx, since) -> raw_items[]`
- `normalize(raw_item) -> canonical_note`
- `write_note(canonical_note, library_path) -> note_path`

No Python-level Q&A contract remains in the package.

## Zhihu Implementation
Zhihu supports three acquisition modes:
- browser-discovered page ingestion
- authenticated API-backed ingestion
- manual seed ingestion from URLs or saved HTML

The stable path is:
1. save a real logged-in browser session with `sni auth zhihu`
2. reuse that session for acquisition
3. prefer API-backed extraction when the session can access the data
4. fall back to page discovery and page fetch when needed

## WeChat Implementation
WeChat supports:
- seed article ingestion
- browser-session page fetch
- `discover wechat`, which derives `mp/profile_ext?action=getmsg` from a reachable seed article and paginates through history
- streaming note materialization while the browser queue is still being consumed
- verification-aware resume based on library state

The history source is `profile_ext/getmsg`, not cached links.

## Library Storage Model
Library layout:
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
`sni` is ingestion-only:
- `sni auth <source>`
- `sni ingest <source> --target <file>`
- `sni discover wechat --target <file>`
- `sni verify zhihu --target <file> --library <path>`

## notes-rg-qa
The retrieval layer is intentionally small:
- no separate retrieval index
- no session persistence
- no model-specific CLI wrappers
- no editor-specific API requirement

Agents search the note library with `rg`, open the relevant note files, and answer from raw evidence.
