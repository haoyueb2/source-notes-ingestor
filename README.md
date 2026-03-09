# obsidian-knowledge-ingestor

A local-first ingestion pipeline for collecting Zhihu and WeChat content, normalizing it into Markdown, storing it inside an Obsidian vault, and querying the vault through the official Obsidian CLI.

## Docs
- [Technical Guide (English)](docs/technical.md)
- [技术文档（中文）](docs/technical.zh-CN.md)
- [Architecture](docs/architecture.md)
- [Delivery Plan](docs/plan.md)

## What is implemented now
- A runnable Python package and CLI: `oki`
- Source adapters for feed-driven, manual-seed, and browser-session Zhihu/WeChat ingestion
- Browser-session login persistence via Playwright
- WeChat history discovery through `discover wechat`, using `seed article -> profile_ext/getmsg -> paginated article list`
- WeChat streaming ingestion, so Markdown notes appear while the crawl is still running
- WeChat verification-aware resume, so `oki ingest wechat` can recompute remaining URLs from state and retry after a verification wall
- HTML-to-Markdown normalization into a canonical note model
- Obsidian vault writer with frontmatter, raw HTML archival, asset download, and sync state tracking
- Scope-based QA package builder plus agentic vault Q&A via Codex + official Obsidian CLI
- Unit tests for normalization, note writing, incremental skip behavior, WeChat verification-wall detection, and browser URL discovery

## What is not implemented yet
- Fully unattended login or captcha solving
- Full-history WeChat account extraction for accounts that do not expose a usable `profile_ext/getmsg` path from a reachable seed article
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
- `scopes/`: person-level scope definitions for the QA layer

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
- `Derived/Scopes/<scope_id>/*.md`
- `Sources/_assets/...`
- `Sources/_state/...`

## Querying with Obsidian CLI
The agent-facing query layer assumes the official Obsidian CLI is enabled from the desktop app and exposed in `PATH`.

Important:
- This project rejects the npm `obsidian-cli` package.
- It expects the official Obsidian desktop CLI from Obsidian Settings > General > Command line interface.
- `oki ask` now uses a stabilized two-stage orchestration:
  1. preload the derived scope map
  2. let local Codex generate a structured retrieval plan
  3. execute raw-note retrieval programmatically through the official Obsidian CLI
  4. ask Codex to synthesize a long-form answer from the raw evidence bundle

This is deliberate. An earlier design relied on Codex directly deciding when to call `qa-search` and `qa-read` during `codex exec`. Live runs showed that path was not stable enough. The current design keeps Codex for deep interpretation and synthesis, while moving the actual vault retrieval loop back into deterministic program code.

Examples:
```bash
oki search "deepseek"
oki read "Sources/Zhihu/example-author/answers/123-some-title.md"
oki build-qa --scope linlin
oki qa-search --scope linlin --query "成长 自律"
oki qa-open-derived --scope linlin --kind overview
oki ask "这个人最近怎么看 AI Agent" --scope linlin
oki ask "这个人最近怎么看 AI Agent" --scope linlin --context-mode fulltext
```

## Running the QA layer
Recommended environment for the local Codex-backed QA flow:

```bash
cd /Users/haoyuebai/Dev/ai/obsidian-knowledge-ingestor
source .venv/bin/activate
export PYTHONPATH=src
export OBSIDIAN_VAULT_PATH=/Users/haoyuebai/Documents/oki-main-vault
export OKI_CODEX_MODEL=gpt-5.4
export OKI_CODEX_REASONING_EFFORT=high
export OKI_CODEX_STREAM=1
```

Build or rebuild the scope package:

```bash
python3 -m obsidian_knowledge_ingestor.cli build-qa --scope linlin --vault /Users/haoyuebai/Documents/oki-main-vault --rebuild
```

Ask in default `map` mode:

```bash
python3 -m obsidian_knowledge_ingestor.cli ask '感到无聊老想出去玩social是对的吗' --scope linlin --vault /Users/haoyuebai/Documents/oki-main-vault --context-mode map
```

Ask in higher-cost `fulltext` mode:

```bash
python3 -m obsidian_knowledge_ingestor.cli ask '感到无聊老想出去玩social是对的吗' --scope linlin --vault /Users/haoyuebai/Documents/oki-main-vault --context-mode fulltext
```

What you should expect at runtime:
- `build-qa` streams Codex output when `OKI_CODEX_STREAM=1`, so you can watch the overview/theme generation live.
- `oki ask` prints retrieval progress such as `[oki ask] planning retrieval` and `[oki ask] searching ...`.
- The final long-form answer is emitted once, after the raw evidence bundle has been collected and synthesized.
- `map` mode preloads `overview`, `themes`, and `corpus_index`, then retrieves raw notes.
- `fulltext` mode additionally preloads a truncated `full_context` extract, so it is materially more expensive in prompt size.

## Scope config
The QA layer works at a person-level scope and can aggregate multiple source roots for the same creator.

Example:
```json
{
  "scope_id": "linlin",
  "display_name": "林琳",
  "sources": [
    {
      "path": "Sources/Zhihu/lin-lin-98-23",
      "source": "zhihu",
      "author_id": "lin-lin-98-23",
      "author_name": "lin-lin-98-23"
    },
    {
      "path": "Sources/WeChat/大魔王的后花园",
      "source": "wechat",
      "account_name": "大魔王的后花园"
    }
  ]
}
```

`oki build-qa --scope ...` writes deterministic derived files plus Codex-generated scope maps under `Derived/Scopes/<scope_id>/`.

The generated files are split by responsibility:
- Program-generated deterministic files:
  - `manifest.md`
  - `corpus_index.md`
  - `full_context.md`
- Codex-generated derived maps:
  - `overview.md`
  - `themes.md`

`overview.md` is intended to be a long-form orientation document. `themes.md` is intended to be a dense retrieval atlas rather than a short topical summary.

## Current strategy
- Zhihu: logged-in browser automation plus API-backed ingestion and post-ingest verification.
- WeChat: use one or more seed article URLs to derive a `profile_ext/getmsg` history feed, page through article history, then fetch article bodies with the browser session.
- Local WeChat cache is used only to recover seed URLs with the required query parameters. It is not treated as a source of truth for history discovery.
- WeChat ingestion writes notes incrementally and relies on `Sources/_state` to resume after verification walls or process interruptions.
- The vault remains the only agent-facing source of truth.

## QA cost notes
- The tested serious-answer flow that asked `感到无聊老想出去玩social是对的吗` was run in `--context-mode map`, not `fulltext`.
- One measured successful run used `35,623` tokens total across the planning stage and final synthesis stage.
- A later stabilized rerun used the same `map` path, with planning alone at `28,930` tokens; the final synthesis stage was non-streamed, so the exact total for that rerun was not exposed by the local CLI.
- This repository does not know how to map local Codex token usage to an exact percentage of a 5-hour quota. The local CLI exposes per-run token counts, but not the quota denominator.
