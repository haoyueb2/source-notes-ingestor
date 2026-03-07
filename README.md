# obsidian-knowledge-ingestor

A local-first ingestion pipeline for collecting Zhihu and WeChat content, normalizing it into Markdown, storing it inside an Obsidian vault, and querying the vault through the official Obsidian CLI.

## What is implemented now
- A runnable Python package and CLI: `oki`
- Source adapters for feed-driven, manual-seed, and browser-session Zhihu/WeChat ingestion
- Browser-session login persistence via Playwright
- HTML-to-Markdown normalization into a canonical note model
- Obsidian vault writer with frontmatter, raw HTML archival, asset download, and sync state tracking
- Obsidian CLI query wrapper for `search`, `read`, and `ask`
- Unit tests for normalization, note writing, incremental skip behavior, WeChat verification-wall detection, and browser URL discovery

## What is not implemented yet
- Fully unattended login or captcha solving
- Full-history WeChat account extraction from a seed article without an accessible history surface
- Scheduler, retries, structured logging, or containerization
- High-maintenance anti-bot modules

## Real-world constraint discovered during live checks
- Zhihu profile pages can return `HTTP 403` to non-browser collection.
- WeChat article pages can return a human-verification wall instead of article content.
- Because of that, the current system supports four ingestion modes:
  - `feed_url`: preferred when an RSS-style source is available
  - `page_urls`: direct URL seeds when a page is accessible from the current session
  - `html_paths`: saved HTML files when the live page requires login or verification
  - `browser`: a persisted Playwright login session used by `oki auth` + `oki ingest`

## Install
```bash
cd /Users/haoyuebai/Dev/ai/obsidian-knowledge-ingestor
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[browser]
python3 -m playwright install chromium
```

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

## Login session bootstrap
Save a browser session once per source:
```bash
oki auth zhihu
oki auth wechat --login-url 'https://mp.weixin.qq.com/s/PgR1HF-b9r7V37iwNNCgrw'
```

By default, this saves storage state under `./state/browser/<source>.json`.

## Quick start
1. Set `OBSIDIAN_VAULT_PATH` to your target vault.
2. Copy one of the sample target files and replace the source fields.
3. Run `oki auth <source>` once to complete login or human verification in a real browser.
4. Run `oki ingest <source> --target ...`.
5. Use `oki search`, `oki read`, or `oki ask` once the official Obsidian CLI is available in `PATH`.

Example:
```bash
export OBSIDIAN_VAULT_PATH=/absolute/path/to/your/vault
cp samples/zhihu_target.example.json /tmp/zhihu_target.json
oki auth zhihu
oki ingest zhihu --target /tmp/zhihu_target.json
```

## Target config shape
Zhihu target example:
```json
{
  "author_id": "lin-lin-98-23",
  "author_name": "lin-lin-98-23",
  "profile_url": "https://www.zhihu.com/people/lin-lin-98-23",
  "browser": {
    "enabled": true,
    "storage_state": "./state/browser/zhihu.json",
    "channel": "chrome",
    "headless": true,
    "scroll_steps": 8,
    "delay_ms": 900,
    "max_items": 60
  }
}
```

WeChat target example:
```json
{
  "account_name": "大魔王的后花园",
  "page_urls": [
    "https://mp.weixin.qq.com/s/PgR1HF-b9r7V37iwNNCgrw"
  ],
  "browser": {
    "enabled": true,
    "storage_state": "./state/browser/wechat.json",
    "channel": "chrome",
    "headless": true,
    "scroll_steps": 2,
    "delay_ms": 800,
    "max_items": 30,
    "discover_from_seed": true
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

## Current strategy
- Zhihu: browser session discovery from the profile URL, then fetch the discovered answers, posts, and pins.
- WeChat: browser session fetch from one or more seed article URLs, then discover same-domain article links exposed from those pages.
- The vault remains the only agent-facing source of truth.
