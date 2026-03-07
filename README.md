# obsidian-knowledge-ingestor

A local-first ingestion pipeline for collecting Zhihu and WeChat content, normalizing it into Markdown, storing it inside an Obsidian vault, and querying the vault through the official Obsidian CLI.

## What is implemented now
- A runnable Python package and CLI: `oki`
- Source adapters for feed-driven Zhihu and WeChat ingestion
- HTML-to-Markdown normalization into a canonical note model
- Obsidian vault writer with frontmatter, raw HTML archival, asset download, and sync state tracking
- Obsidian CLI query wrapper for `search`, `read`, and `ask`
- Unit tests for normalization, note writing, and incremental skip behavior

## What is not implemented yet
- Full logged-in browser automation for Zhihu author pages
- Full-history WeChat account extraction without an RSS-style source
- Scheduler, retries, structured logging, or containerization
- High-maintenance anti-bot modules

## Project layout
- `src/obsidian_knowledge_ingestor/`: runtime package
- `docs/architecture.md`: architecture contract and boundaries
- `docs/plan.md`: staged delivery plan
- `samples/*.example.json`: target config examples
- `tests/`: unit tests

## Fixed interfaces
These logical interfaces remain the contract for future work:
- `fetch_source(target, auth_ctx, since) -> raw_items[]`
- `normalize(raw_item) -> canonical_note`
- `write_note(canonical_note, vault_path) -> note_path`
- `query_vault(prompt, scope) -> results`

## Quick start
1. Create a virtual environment and install the package in editable mode.
2. Set `OBSIDIAN_VAULT_PATH` to your target vault.
3. Copy one of the sample target files and replace the feed URL plus auth fields.
4. Run `oki ingest` for the source you want.
5. Use `oki search`, `oki read`, or `oki ask` once the official Obsidian CLI is available in `PATH`.

Example:
```bash
cd /Users/haoyuebai/Dev/ai/obsidian-knowledge-ingestor
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
export OBSIDIAN_VAULT_PATH=/absolute/path/to/your/vault
cp samples/zhihu_target.example.json /tmp/zhihu_target.json
oki ingest zhihu --target /tmp/zhihu_target.json
```

## Target config shape
Zhihu feed target example:
```json
{
  "feed_url": "https://rsshub.example.com/zhihu/people/example/answers",
  "author_id": "example-author",
  "author_name": "Example Author",
  "auth_ctx": {
    "cookie": "z_c0=your_cookie_here",
    "user_agent": "Mozilla/5.0"
  }
}
```

WeChat feed target example:
```json
{
  "feed_url": "https://we-mp-rss.example.com/account/example/feed.xml",
  "account_id": "example-account",
  "account_name": "Example Account",
  "auth_ctx": {
    "cookie": "appmsg_token=your_token_here",
    "user_agent": "Mozilla/5.0"
  }
}
```

## Vault layout
- `Sources/Zhihu/<author>/answers/*.md`
- `Sources/Zhihu/<author>/thoughts/*.md`
- `Sources/Zhihu/<author>/articles/*.md`
- `Sources/WeChat/<account>/*.md`
- `Sources/_assets/...`
- `Sources/_state/...`

## Querying with Obsidian CLI
The query layer assumes the official Obsidian CLI is enabled from the desktop app and exposed in `PATH`.

Examples:
```bash
oki search "deepseek"
oki read "Sources/Zhihu/example-author/answers/123-some-title.md"
oki ask "这个人最近怎么看 AI Agent" --scope "Example Author"
```

## Source strategy
- Zhihu: RSS or another stable public feed first, then logged-in fetchers later.
- WeChat: RSS-style conversion flow first, backfill exporter later.
- The vault remains the only agent-facing source of truth.
