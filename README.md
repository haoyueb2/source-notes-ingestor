# obsidian-knowledge-ingestor

A local-first knowledge ingestion system for collecting content from Zhihu authors and WeChat official accounts, normalizing it into Markdown, storing it in an Obsidian vault, and querying it through the official Obsidian CLI.

## Goals
- Ingest all public or lawfully accessible content from a target Zhihu author: answers, thoughts, and articles.
- Ingest all historical and incremental articles from a target WeChat official account.
- Normalize source content into a consistent canonical note model.
- Write clean Markdown notes plus assets into an Obsidian vault.
- Let Claude/Codex query the vault through the official Obsidian CLI rather than raw crawler output.

## System Components
- `source adapters`: fetch from Zhihu and WeChat with a mixed strategy.
- `normalizer`: convert raw source payloads into a canonical note model.
- `vault_writer`: persist canonical notes into the target vault layout.
- `qa_runner`: wrap official Obsidian CLI commands for search and note retrieval.
- `state`: track incremental sync checkpoints and deduplication metadata.

## Fixed Interfaces
The implementation must preserve these logical interfaces, regardless of language choice:
- `fetch_source(target, auth_ctx, since) -> raw_items[]`
- `normalize(raw_item) -> canonical_note`
- `write_note(canonical_note, vault_path) -> note_path`
- `query_vault(prompt, scope) -> results`

## Vault Layout
- `Sources/Zhihu/<author>/answers/*.md`
- `Sources/Zhihu/<author>/thoughts/*.md`
- `Sources/Zhihu/<author>/articles/*.md`
- `Sources/WeChat/<account>/*.md`
- `Sources/_assets/...`
- `Sources/_state/...`

## Current Status
This repository is scaffold-only.
- No crawler implementation yet.
- No locked language/runtime yet.
- No dependency installation or lockfiles.
- The first milestone is to preserve architecture decisions and repo boundaries.

## Non-Goals for v1
- Comments, favorites, likes, private content, or paid content.
- Cloud-only deployment.
- Direct agent access to raw crawler data.
- Full anti-bot reverse engineering as the default path.

## Suggested Next Step
Finalize the implementation stack for v0 and then build the adapter and writer skeletons against the interfaces documented here.
