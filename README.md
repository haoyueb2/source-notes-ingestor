# obsidian-knowledge-ingestor

A local-first ingestion pipeline for collecting Zhihu and WeChat content, normalizing it into Markdown, and storing it inside an Obsidian vault.

The repository no longer ships a built-in QA product layer. `oki` is now ingestion-only. Vault Q&A is provided as an in-repo Codex plugin/skill that requires the official Obsidian CLI.

## Docs
- [Technical Guide (English)](docs/technical.md)
- [技术文档（中文）](docs/technical.zh-CN.md)
- [Architecture](docs/architecture.md)
- [Delivery Plan](docs/plan.md)

Recommended reading order:
1. Read `README.md` for the end-to-end ingestion workflow.
2. Read the technical guide for design tradeoffs.
3. Inspect `src/obsidian_knowledge_ingestor/`.
4. Use `tests/` to understand the protected ingestion behavior.

## What is implemented now
- A runnable Python package and CLI: `oki`
- Source adapters for feed-driven, manual-seed, and browser-session Zhihu/WeChat ingestion
- Browser-session login persistence via Playwright
- WeChat history discovery through `discover wechat`, using `seed article -> profile_ext/getmsg -> paginated article list`
- WeChat streaming ingestion, so Markdown notes appear while the crawl is still running
- WeChat verification-aware resume, so `oki ingest wechat` can recompute remaining URLs from state and retry after a verification wall
- HTML-to-Markdown normalization into a canonical note model
- Obsidian vault writer with frontmatter, raw HTML archival, asset download, and sync state tracking
- A repo-local Obsidian QA plugin/skill under `plugins/obsidian-qa/`

## What is not implemented
- Built-in vault QA commands inside `oki`
- Fully unattended login or captcha solving
- Full-history WeChat extraction for accounts that do not expose a usable `profile_ext/getmsg` path from a reachable seed article
- Scheduler, retries beyond current local recovery loops, structured logging, or containerization
- High-maintenance anti-bot modules

## Install
```bash
cd /Users/haoyuebai/Dev/ai/obsidian-knowledge-ingestor
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[browser]
python3 -m playwright install chromium
```

## Project layout
- `src/obsidian_knowledge_ingestor/`: ingestion runtime package
- `plugins/obsidian-qa/`: model-agnostic Obsidian QA plugin and skill
- `docs/architecture.md`: architecture contract and boundaries
- `docs/plan.md`: staged delivery plan
- `samples/*.example.json`: target config examples
- `tests/`: unit tests

## Fixed interfaces
These ingestion interfaces remain the core contract:
- `fetch_source(target, auth_ctx, since) -> raw_items[]`
- `normalize(raw_item) -> canonical_note`
- `write_note(canonical_note, vault_path) -> note_path`

The QA path is no longer a Python interface in this package. Agents should use the in-repo plugin/skill plus the official Obsidian CLI.

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
5. Use the Obsidian QA plugin/skill for retrieval and synthesis.

Example:
```bash
export OBSIDIAN_VAULT_PATH=/absolute/path/to/your/vault
cp samples/zhihu_target.example.json /tmp/zhihu_target.json
oki auth zhihu
oki ingest zhihu --target /tmp/zhihu_target.json
```

WeChat history workflow:
```bash
export OBSIDIAN_VAULT_PATH=/absolute/path/to/your/vault
oki auth wechat --login-url 'https://mp.weixin.qq.com/s/PgR1HF-b9r7V37iwNNCgrw'
oki discover wechat --target targets/wechat_damowang.json
oki ingest wechat --target targets/wechat_damowang_discovered.json
```

Progress monitoring:
```bash
./scripts/watch_wechat_progress.sh "$OBSIDIAN_VAULT_PATH"
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

## Obsidian QA plugin
The repository includes a model-agnostic plugin scaffold for vault Q&A:
- plugin manifest: `plugins/obsidian-qa/.codex-plugin/plugin.json`
- skill: `plugins/obsidian-qa/skills/obsidian-cli-qa/SKILL.md`
- marketplace entry: `.agents/plugins/marketplace.json`

The skill requires the official Obsidian desktop CLI from Obsidian Settings > General > Command line interface. It explicitly routes agents to:
1. plan the question
2. run multiple short `obsidian search` queries
3. open matching notes with `obsidian read`
4. answer from raw note evidence only

## Running tests
```bash
cd /Users/haoyuebai/Dev/ai/obsidian-knowledge-ingestor
source .venv/bin/activate
PYTHONPATH=src python -m unittest discover -s tests
```
