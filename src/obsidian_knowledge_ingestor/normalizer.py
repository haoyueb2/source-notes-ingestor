from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .html_tools import extract_main_html, extract_summary, extract_title, html_to_markdown
from .models import CanonicalNote, RawItem
from .utils import sha256_text


def normalize(raw_item: RawItem) -> CanonicalNote:
    extracted_html = extract_main_html(raw_item.raw_html, raw_item.source)
    markdown_body, assets = html_to_markdown(extracted_html, raw_item.url)
    title = raw_item.title or extract_title(raw_item.raw_html) or raw_item.content_id
    summary = raw_item.summary or extract_summary(raw_item.raw_html) or ""
    checksum = sha256_text("\n".join([raw_item.url, title, markdown_body]))

    return CanonicalNote(
        source=raw_item.source,
        author_id=raw_item.author_id,
        author_name=raw_item.author_name,
        content_id=raw_item.content_id,
        content_type=raw_item.content_type,
        title=title,
        url=raw_item.url,
        published_at=raw_item.published_at,
        updated_at=raw_item.updated_at,
        tags=raw_item.tags,
        summary=summary,
        markdown_body=markdown_body,
        raw_html_path=None,
        assets=assets,
        checksum=checksum,
    )
