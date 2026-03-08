from __future__ import annotations

import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from .config import AppConfig
from .models import CanonicalNote
from .utils import dump_json, ensure_dir, load_json, slugify


def _note_directory(note: CanonicalNote, config: AppConfig) -> Path:
    if note.source == "zhihu":
        return config.vault_path / "Sources" / "Zhihu" / slugify(note.author_name) / f"{note.content_type}s"
    return config.vault_path / "Sources" / "WeChat" / slugify(note.author_name)


def _state_path(note: CanonicalNote, config: AppConfig) -> Path:
    return config.vault_path / config.sync_state_dir_name / f"{note.source}-{slugify(note.author_name)}.json"


def _asset_directory(note: CanonicalNote, config: AppConfig) -> Path:
    return config.vault_path / config.asset_dir_name / note.source / slugify(note.author_name) / note.content_id


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _frontmatter(note: CanonicalNote, raw_html_relpath: str | None) -> str:
    tags = "[" + ", ".join(f'"{tag}"' for tag in note.tags) + "]"
    assets = "[" + ", ".join(f'"{item}"' for item in note.assets) + "]"
    lines = [
        "---",
        f'source: "{note.source}"',
        f'author_id: "{note.author_id}"',
        f'author_name: "{note.author_name}"',
        f'content_id: "{note.content_id}"',
        f'content_type: "{note.content_type}"',
        f'title: "{note.title.replace(chr(34), chr(39))}"',
        f'url: "{note.url}"',
        f'published_at: {_yaml_scalar(_serialize_datetime(note.published_at))}',
        f'updated_at: {_yaml_scalar(_serialize_datetime(note.updated_at))}',
        f'tags: {tags}',
        f'summary: "{note.summary.replace(chr(34), chr(39))}"',
        f'assets: {assets}',
        f'checksum: "{note.checksum}"',
        f'raw_html_path: {_yaml_scalar(raw_html_relpath)}',
        f'ingested_at: "{datetime.now(tz=UTC).isoformat()}"',
        "---",
        "",
    ]
    return "\n".join(lines)


def _yaml_scalar(value: str | None) -> str:
    return f'"{value}"' if value is not None else "null"


def _note_file_name(note: CanonicalNote, note_dir: Path) -> str:
    title_slug = slugify(note.title)
    preferred = f"{title_slug}.md"
    preferred_path = note_dir / preferred
    if not preferred_path.exists():
        return preferred

    fallback = f"{title_slug}-{note.content_id}.md"
    return fallback


def _download_asset(url: str, dest_dir: Path) -> str | None:
    parsed = urlparse(url)
    name = Path(parsed.path).name or "asset"
    target = dest_dir / name
    try:
        ensure_dir(dest_dir)
        urllib.request.urlretrieve(url, target)
        return target.name
    except Exception:
        return None


def _rewrite_assets(markdown_body: str, original_assets: list[str], local_assets: dict[str, str], asset_root: Path, vault_path: Path) -> tuple[str, list[str]]:
    body = markdown_body
    refs: list[str] = []
    for asset in original_assets:
        local_name = local_assets.get(asset)
        if not local_name:
            refs.append(asset)
            continue
        rel = str((asset_root / local_name).relative_to(vault_path))
        body = body.replace(asset, rel)
        refs.append(rel)
    return body, refs


def write_note(
    note: CanonicalNote,
    vault_path: str | Path,
    config: AppConfig | None = None,
    raw_html: str | None = None,
) -> Path:
    cfg = config or AppConfig.from_env()
    cfg = AppConfig(
        vault_path=Path(vault_path).expanduser(),
        state_dir=cfg.state_dir,
        raw_data_dir=cfg.raw_data_dir,
        asset_dir_name=cfg.asset_dir_name,
        sync_state_dir_name=cfg.sync_state_dir_name,
        log_level=cfg.log_level,
    )

    note_dir = ensure_dir(_note_directory(note, cfg))
    file_name = _note_file_name(note, note_dir)
    note_path = note_dir / file_name

    raw_dir = ensure_dir(cfg.raw_data_dir / note.source / slugify(note.author_name))
    raw_html_path = raw_dir / f"{note.content_id}.html"
    raw_html_relpath = str(raw_html_path)

    asset_dir = _asset_directory(note, cfg)
    downloaded: dict[str, str] = {}
    for asset in note.assets:
        local_name = _download_asset(asset, asset_dir)
        if local_name:
            downloaded[asset] = local_name

    markdown_body, asset_refs = _rewrite_assets(note.markdown_body, note.assets, downloaded, asset_dir, cfg.vault_path)
    materialized_note = CanonicalNote(
        source=note.source,
        author_id=note.author_id,
        author_name=note.author_name,
        content_id=note.content_id,
        content_type=note.content_type,
        title=note.title,
        url=note.url,
        published_at=note.published_at,
        updated_at=note.updated_at,
        tags=note.tags,
        summary=note.summary,
        markdown_body=markdown_body,
        raw_html_path=raw_html_path,
        assets=asset_refs,
        checksum=note.checksum,
    )

    if raw_html is not None:
        raw_html_path.write_text(raw_html, encoding="utf-8")
    note_path.write_text(_frontmatter(materialized_note, raw_html_relpath) + markdown_body, encoding="utf-8")

    state_path = _state_path(note, cfg)
    state = load_json(state_path)
    state.setdefault("items", {})
    state["items"][note.content_id] = {
        "checksum": note.checksum,
        "note_path": str(note_path.relative_to(cfg.vault_path)),
        "updated_at": _serialize_datetime(note.updated_at),
        "published_at": _serialize_datetime(note.published_at),
    }
    state["last_sync_at"] = datetime.now(tz=UTC).isoformat()
    dump_json(state_path, state)

    return note_path
