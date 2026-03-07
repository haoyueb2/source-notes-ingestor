# obsidian-knowledge-ingestor

A local-first ingestion pipeline for collecting Zhihu and WeChat content, normalizing it into Markdown, storing it inside an Obsidian vault, and querying the vault through the official Obsidian CLI.

## What is implemented now
- A runnable Python package and CLI: `oki`
- Source adapters for feed-driven and manual-seed Zhihu/WeChat ingestion
- HTML-to-Markdown normalization into a canonical note model
- Obsidian vault writer with frontmatter, raw HTML archival, asset download, and sync state tracking
- Obsidian CLI query wrapper for `search`, `read`, and `ask`
- Unit tests for normalization, note writing, incremental skip behavior, and WeChat verification-wall detection

## What is not implemented yet
- Full logged-in browser automation for Zhihu author pages
- Full-history WeChat account extraction without an RSS-style source or saved HTML
- Scheduler, retries, structured logging, or containerization
- High-maintenance anti-bot modules

## Real-world constraint discovered during live checks
- Zhihu profile pages can return `HTTP 403` to non-browser collection.
- WeChat article pages can return a human-verification wall instead of article content.
- Because of that, the current minimum viable system supports three ingestion modes:
  - `feed_url`: preferred when an RSS-style source is available
  - `page_urls`: direct URL seeds when a page is accessible from the current session
  - `html_paths`: saved HTML files when the live page requires login or verification

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
3. Copy one of the sample target files and replace the source fields.
4. Run `oki ingest` for the source you want.
5. Use `oki search`, `oki read`, or `oki ask` once the official Obsidian CLI is available in `PATH`.

Example:
```bash
cd /Users/haoyuebai/Dev/ai/obsidian-knowledge-ingestor
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
export OBSIDIAN_VAULT_PATH=/absolute/path/to/your/vault
cp samples/wechat_target.example.json /tmp/wechat_target.json
oki ingest wechat --target /tmp/wechat_target.json
```

## Target config shape
Zhihu target example:
```json
{
  "feed_url": "https://rsshub.example.com/zhihu/people/example/answers",
  "author_id": "example-author",
  "author_name": "Example Author",
  "auth_ctx": {
    "cookie": "z_c0=your_cookie_here",
    "user_agent": "Mozilla/5.0"
  },
  "page_urls": [
    "https://www.zhihu.com/question/1/answer/123"
  ],
  "html_paths": [
    "/absolute/path/to/saved-answer.html"
  ]
}
```

WeChat target example:
```json
{
  "feed_url": "https://we-mp-rss.example.com/account/example/feed.xml",
  "account_id": "example-account",
  "account_name": "Example Account",
  "auth_ctx": {
    "cookie": "appmsg_token=your_token_here",
    "user_agent": "Mozilla/5.0"
  },
  "page_urls": [
    "https://mp.weixin.qq.com/s/your-article-url"
  ],
  "html_paths": [
    "/absolute/path/to/saved-article.html"
  ]
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
- WeChat: RSS-style conversion flow first, saved HTML or backfill exporter next.
- The vault remains the only agent-facing source of truth.
