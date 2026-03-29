# source-notes-ingestor

A local-first ingestion pipeline for collecting Zhihu and WeChat content, normalizing it into Markdown, and storing it inside a local notes library.

This repository intentionally does less than it used to. The package focuses on ingestion only. Search-oriented Q&A is now handled by a lightweight repo-local skill/plugin that uses `rg` plus direct note reads instead of a dedicated CLI orchestration layer.

## Docs
- [Technical Guide (English)](docs/technical.md)
- [技术文档（中文）](docs/technical.zh-CN.md)
- [Architecture](docs/architecture.md)
- [Delivery Plan](docs/plan.md)

## What is implemented now
- A runnable Python package and CLI: `sni`
- Source adapters for feed-driven, manual-seed, and browser-session Zhihu/WeChat ingestion
- Browser-session login persistence via Playwright
- WeChat history discovery through `discover wechat`, using `seed article -> profile_ext/getmsg -> paginated article list`
- WeChat streaming ingestion, so notes appear while the crawl is still running
- WeChat verification-aware resume, so `sni ingest wechat` can recompute remaining URLs from state and retry after a verification wall
- HTML-to-Markdown normalization into a canonical note model
- Markdown library writing with frontmatter, raw HTML archival, asset download, and sync state tracking
- A repo-local `notes-rg-qa` plugin/skill under `plugins/notes-rg-qa/`

## What is intentionally not implemented
- Built-in Q&A commands inside `sni`
- A dedicated model-specific CLI layer for Claude, Codex, or similar agents
- A required editor-specific retrieval backend
- Fully unattended login or captcha solving
- Full-history WeChat extraction for accounts that do not expose a usable `profile_ext/getmsg` path from a reachable seed article

## Install
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[browser]
python3 -m playwright install chromium
```

## Project layout
- `src/source_notes_ingestor/`: ingestion runtime package
- `plugins/notes-rg-qa/`: repo-local search skill/plugin for agents
- `docs/`: architecture and technical notes
- `samples/`: target config examples
- `tests/`: ingestion-focused tests

## Stable ingestion interfaces
- `fetch_source(target, auth_ctx, since) -> raw_items[]`
- `normalize(raw_item) -> canonical_note`
- `write_note(canonical_note, library_path) -> note_path`

## Login session bootstrap
```bash
sni auth zhihu
sni auth wechat --login-url 'https://mp.weixin.qq.com/s/PgR1HF-b9r7V37iwNNCgrw'
```

By default, this saves storage state under `./state/browser/<source>.json`.

## Quick start
1. Set `NOTES_LIBRARY_PATH` to your target notes library.
2. Copy one of the sample target files and replace the source fields.
3. Run `sni auth <source>` once to complete login or human verification in a real browser.
4. Run `sni ingest <source> --target ...`.
5. Use the `notes-rg-qa` skill/plugin for retrieval and synthesis.

Example:
```bash
export NOTES_LIBRARY_PATH=/absolute/path/to/your/library
cp samples/zhihu_target.example.json /tmp/zhihu_target.json
sni auth zhihu
sni ingest zhihu --target /tmp/zhihu_target.json
```

WeChat history workflow:
```bash
export NOTES_LIBRARY_PATH=/absolute/path/to/your/library
sni auth wechat --login-url 'https://mp.weixin.qq.com/s/PgR1HF-b9r7V37iwNNCgrw'
sni discover wechat --target targets/wechat_damowang.json
sni ingest wechat --target targets/wechat_damowang_discovered.json
```

Progress monitoring:
```bash
./scripts/watch_wechat_progress.sh "$NOTES_LIBRARY_PATH"
```

## Library layout
- `Sources/Zhihu/<author>/answers/*.md`
- `Sources/Zhihu/<author>/thoughts/*.md`
- `Sources/Zhihu/<author>/articles/*.md`
- `Sources/WeChat/<account>/*.md`
- `Sources/_assets/...`
- `Sources/_state/...`

## notes-rg-qa plugin
The repository includes a small, model-agnostic plugin scaffold for note-library Q&A:
- plugin manifest: `plugins/notes-rg-qa/.codex-plugin/plugin.json`
- skill: `plugins/notes-rg-qa/skills/notes-rg-qa/SKILL.md`
- marketplace entry: `.agents/plugins/marketplace.json`

The skill explicitly tells agents to:
1. plan a question in retrieval-friendly terms
2. use `rg` for multiple short searches
3. open raw note files directly
4. answer from opened evidence only

## Running tests
```bash
source .venv/bin/activate
PYTHONPATH=src python -m unittest discover -s tests
```
