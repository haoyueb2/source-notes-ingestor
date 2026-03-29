# Architecture

## Overview
`obsidian-knowledge-ingestor` is a local-first ingestion system that:
1. fetches public Zhihu and WeChat content
2. normalizes it into a stable note model
3. stores the result in an Obsidian vault

Vault Q&A is intentionally outside the Python runtime. Agents should use the repo-local Obsidian QA plugin/skill, which itself must use the official Obsidian CLI.

Pipeline:
1. `source adapter` fetches raw items for a target author/account
2. `normalizer` maps each raw item into the canonical note model
3. `vault_writer` stores Markdown, frontmatter, assets, and sync metadata
4. `obsidian-qa` plugin/skill retrieves raw notes through the official Obsidian CLI

## Source Strategy

### Zhihu
Primary and fallback acquisition paths are fixed in this order:
1. stable public entry points when available
2. logged-in page fetching with browser automation for author answers, thoughts, and articles
3. isolated high-maintenance anti-bot modules only when the first two layers cannot satisfy coverage requirements

Design constraints:
- logged-in collection is allowed in the local-first setup
- anti-bot logic must remain isolated behind adapter boundaries
- the default path is not full reverse engineering

### WeChat Official Accounts
Primary and fallback acquisition paths are fixed in this order:
1. seed-article-driven history discovery through `mp/profile_ext?action=getmsg`
2. subscription or RSS-conversion style routes when the first path is unavailable
3. per-account backfill tools when the first two layers cannot provide enough coverage
4. public RSS-style routes only as discovery or supplemental inputs

Design constraints:
- target only lawfully accessible public official account articles
- support both a one-time backfill path and an incremental sync path
- local WeChat cache may help recover seed URLs, but it is not treated as authoritative history output

## Canonical Note Model
Every normalized item must produce:
- `source`
- `author_id`
- `author_name`
- `content_id`
- `content_type`
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
- `content_id + checksum` is the dedupe and update key
- source-specific fields may exist before normalization but must not leak into notes except through frontmatter or archived raw payloads
- Markdown output must preserve enough provenance to trace back to the source URL

## Obsidian Vault Contract
The vault layout is fixed as:
- `Sources/Zhihu/<author>/answers/*.md`
- `Sources/Zhihu/<author>/thoughts/*.md`
- `Sources/Zhihu/<author>/articles/*.md`
- `Sources/WeChat/<account>/*.md`
- `Sources/_assets/...`
- `Sources/_state/...`

Each note must contain:
- YAML frontmatter with canonical metadata
- normalized Markdown body
- relative links to downloaded assets
- original source URL and ingestion timestamps in frontmatter

State handling:
- each source keeps independent sync state under `Sources/_state/...`
- state records include successful checkpoints, seen IDs, and retry bookkeeping
- incremental sync appends new items and overwrites existing notes only when checksum changes

## QA Boundary
The Python package does not provide a QA runtime anymore.

Responsibilities of the repo-local plugin/skill:
- require the official Obsidian CLI
- search candidate notes with short retrieval-friendly queries
- read matched raw notes
- synthesize answers from raw note evidence only

Non-responsibilities of the Python package:
- no derived scope packs
- no internal retrieval planner
- no session persistence for ask workflows
- no duplicated note index outside the vault

This keeps the vault as the single source of truth and prevents `oki` from becoming a second product layer on top of the vault.
