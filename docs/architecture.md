# Architecture

## Overview
`obsidian-knowledge-ingestor` is a local-first pipeline that ingests content from Zhihu and WeChat official accounts, normalizes each item into a stable document model, stores the result inside an Obsidian vault, and exposes that vault to agents via the official Obsidian CLI.

The system is intentionally split so that source-specific anti-fragility stays inside adapters while all downstream processing remains source-agnostic.

Pipeline:
1. `source adapter` fetches raw items for a target author/account.
2. `normalizer` maps each raw item into the canonical note model.
3. `vault_writer` stores Markdown, frontmatter, assets, and sync metadata.
4. `qa_runner` performs vault-scoped retrieval through the official Obsidian CLI.

## Source Strategy

### Zhihu
Primary and fallback acquisition paths are fixed in this order:
1. `RSSHub` or other stable public entry points for low-maintenance indexing and incremental discovery.
2. Logged-in page fetching with browser automation for author answers, thoughts, and articles.
3. Isolated high-maintenance anti-bot or signature-based modules only when the first two layers cannot satisfy coverage requirements.

Design constraints:
- Logged-in collection is allowed and expected in the local-first setup.
- High-maintenance anti-bot logic must remain isolated behind the same adapter boundary and must not leak into normalization or vault-writing logic.
- The default implementation path is not full reverse engineering.

### WeChat Official Accounts
Primary and fallback acquisition paths are fixed in this order:
1. Seed-article-driven history discovery through `mp/profile_ext?action=getmsg` when a reachable article exposes a usable history surface.
2. `we-mp-rss`-style projects or equivalent subscription/RSS conversion flows when the first path is unavailable or insufficient.
3. `wechat-article-exporter`-style tools for per-account backfill when the first two layers cannot provide enough coverage.
4. RSSHub or similar public routes only as discovery or supplemental inputs, not as the default primary source.

Design constraints:
- The system targets public official account articles and lawfully accessible content only.
- A one-time backfill path and an incremental sync path must both exist, even if they share implementation pieces.
- Local WeChat cache may be used to recover seed URLs or session-derived parameters, but cached article links are not treated as authoritative history discovery output.

## Canonical Note Model
Every normalized item must produce a canonical note object with these fields:
- `source`: `zhihu` or `wechat`
- `author_id`
- `author_name`
- `content_id`
- `content_type`: `answer`, `thought`, or `article`
- `title`
- `url`
- `published_at`
- `updated_at`
- `tags`
- `summary`
- `markdown_body`
- `raw_html_path`
- `assets[]`
- `checksum`

Rules:
- `content_id + checksum` is the dedupe and update key.
- Source-specific raw fields are allowed before normalization but must not leak into vault notes except through frontmatter or archived raw payloads if explicitly added later.
- Markdown output must preserve source links and enough metadata to trace provenance.

## Obsidian Vault Contract
The vault layout is fixed as:
- `Sources/Zhihu/<author>/answers/*.md`
- `Sources/Zhihu/<author>/thoughts/*.md`
- `Sources/Zhihu/<author>/articles/*.md`
- `Sources/WeChat/<account>/*.md`
- `Sources/_assets/...`
- `Sources/_state/...`

Each note must contain:
- YAML frontmatter with canonical metadata.
- Normalized Markdown body.
- Relative links to downloaded assets.
- Original source URL and ingestion timestamps in frontmatter.

State handling:
- Each source keeps independent sync state under `Sources/_state/...`.
- State records must include the last successful sync checkpoint, seen IDs, and retry/error bookkeeping.
- Incremental sync appends new items and overwrites existing notes only when checksum changes.

## Agent Query Path
The agent-facing query layer is constrained to the official Obsidian CLI.

Responsibilities of `qa_runner`:
- Search for candidate notes by query term or scoped prompt.
- Read matched notes or metadata.
- Execute vault-scoped retrieval workflows that compose search plus note reads.

Non-responsibilities:
- It does not talk to live source adapters.
- It does not parse raw source payloads.
- It does not maintain its own parallel document index in v1.

This keeps the operational source of truth inside the vault and makes the vault itself the integration point for Claude/Codex.

## Interfaces
The following logical interfaces are mandatory and must remain valid if the implementation language changes:
- `fetch_source(target, auth_ctx, since) -> raw_items[]`
- `normalize(raw_item) -> canonical_note`
- `write_note(canonical_note, vault_path) -> note_path`
- `query_vault(prompt, scope) -> results`

Behavioral expectations:
- `fetch_source` supports both first-run full sync and later incremental sync.
- `normalize` is deterministic for the same raw input.
- `write_note` is idempotent with respect to `content_id + checksum`.
- `query_vault` operates only on notes already materialized in the vault.

## Operational Boundaries
Included in scope:
- Local execution on the user's machine.
- Cookie/session persistence for logged-in access when required.
- Manual or scheduled sync runs.
- Asset downloading and relative-link rewriting.

Explicitly out of scope for v1:
- Comments, favorites, likes, private content, or paid content.
- Cloud-only deployment.
- Remote multi-user service design.
- Video/audio transcription.
- Direct raw-data retrieval by agents.
