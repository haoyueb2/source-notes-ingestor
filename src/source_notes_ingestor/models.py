from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RawItem:
    source: str
    author_id: str
    author_name: str
    content_id: str
    content_type: str
    title: str
    url: str
    published_at: datetime | None
    updated_at: datetime | None
    summary: str
    raw_html: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CanonicalNote:
    source: str
    author_id: str
    author_name: str
    content_id: str
    content_type: str
    title: str
    url: str
    published_at: datetime | None
    updated_at: datetime | None
    tags: list[str]
    summary: str
    markdown_body: str
    raw_html_path: Path | None
    assets: list[str]
    checksum: str
