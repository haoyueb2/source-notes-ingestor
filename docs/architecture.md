# Architecture

## Overview
`source-notes-ingestor` is a local-first ingestion system that:
1. fetches public Zhihu and WeChat content
2. normalizes it into a stable note model
3. stores the result in a local notes library

Search-oriented Q&A is intentionally outside the Python runtime. Agents should use the repo-local `notes-rg-qa` skill/plugin and retrieve evidence with standard shell tools.

Pipeline:
1. `source adapter` fetches raw items
2. `normalizer` maps each raw item into the canonical note model
3. `library_writer` stores Markdown, frontmatter, assets, and sync metadata
4. `notes-rg-qa` retrieves raw notes with `rg` and direct file reads

## Source Strategy
### Zhihu
Preferred order:
1. stable public entry points when available
2. logged-in page fetching with browser automation
3. isolated high-maintenance modules only when necessary

### WeChat Official Accounts
Preferred order:
1. seed-article-driven history discovery through `mp/profile_ext?action=getmsg`
2. subscription or RSS-style conversions when that path is unavailable
3. per-account backfill tools when necessary

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

`content_id + checksum` remains the dedupe and update key.

## Library Contract
The library layout is fixed as:
- `Sources/Zhihu/<author>/answers/*.md`
- `Sources/Zhihu/<author>/thoughts/*.md`
- `Sources/Zhihu/<author>/articles/*.md`
- `Sources/WeChat/<account>/*.md`
- `Sources/_assets/...`
- `Sources/_state/...`

Each note contains metadata, normalized Markdown, relative asset links, and provenance.

## Retrieval Boundary
The Python package does not provide a retrieval runtime anymore.

Responsibilities of `notes-rg-qa`:
- search candidate notes with `rg`
- open matched raw notes directly
- synthesize answers from raw note evidence only

Non-responsibilities of the Python package:
- no derived context packs
- no retrieval planner
- no session persistence
- no separate note index
