from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .adapters import fetch_wechat_source, fetch_zhihu_source
from .config import AppConfig, load_target
from .models import CanonicalNote
from .normalizer import normalize
from .utils import load_json, parse_datetime, slugify
from .vault_writer import write_note


@dataclass(slots=True)
class IngestReport:
    source: str
    target_name: str
    fetched: int
    written: int
    skipped: int
    note_paths: list[str]


FETCHERS = {
    "zhihu": fetch_zhihu_source,
    "wechat": fetch_wechat_source,
}


def _state_lookup_path(source: str, target: dict, config: AppConfig) -> Path:
    if source == "zhihu":
        name = target.get("author_name") or target.get("author_id") or "zhihu"
    else:
        name = target.get("account_name") or target.get("account_id") or "wechat"
    return config.vault_path / config.sync_state_dir_name / f"{source}-{slugify(name)}.json"


def ingest_source(source: str, target_path: str | Path, config: AppConfig | None = None) -> IngestReport:
    cfg = config or AppConfig.from_env()
    target = load_target(target_path)
    state = load_json(_state_lookup_path(source, target, cfg))
    since = parse_datetime(state.get("last_sync_at"))
    auth_ctx = target.get("auth_ctx")
    raw_items = FETCHERS[source](target, auth_ctx, since)

    fetched = 0
    written = 0
    skipped = 0
    note_paths: list[str] = []
    seen = state.get("items", {})
    for raw_item in raw_items:
        fetched += 1
        print(
            f"[ingest] raw {fetched}: {raw_item.content_type} {raw_item.content_id}",
            file=sys.stderr,
        )
        note = normalize(raw_item)
        existing = seen.get(note.content_id)
        if existing and existing.get("checksum") == note.checksum:
            skipped += 1
            print(f"[ingest] skip {note.content_type} {note.content_id}", file=sys.stderr)
            continue
        note_path = write_note(note, cfg.vault_path, config=cfg, raw_html=raw_item.raw_html)
        note_paths.append(str(note_path))
        written += 1
        print(f"[ingest] wrote {written}: {note_path}", file=sys.stderr)

    target_name = target.get("author_name") or target.get("account_name") or target.get("author_id") or target.get("account_id") or "unknown"
    return IngestReport(
        source=source,
        target_name=target_name,
        fetched=fetched,
        written=written,
        skipped=skipped,
        note_paths=note_paths,
    )
