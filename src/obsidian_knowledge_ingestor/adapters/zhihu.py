from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from ..models import RawItem
from ..utils import slugify
from .feed import fetch_feed_entries, fetch_text, filter_since


def detect_content_type(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if "zhuanlan.zhihu.com" in host or "/p/" in path:
        return "article"
    if "/answer/" in path:
        return "answer"
    if "/pin/" in path or "/moments/" in path:
        return "thought"
    return "article"


def content_id_from_url(url: str) -> str:
    segments = [segment for segment in urlparse(url).path.split("/") if segment]
    return segments[-1] if segments else slugify(url)


def fetch_source(target: dict, auth_ctx: dict | None, since: datetime | None) -> list[RawItem]:
    feed_url = target["feed_url"]
    author_id = target.get("author_id") or slugify(target.get("author_name", "zhihu-author"))
    author_name = target.get("author_name") or author_id
    entries = filter_since(fetch_feed_entries(feed_url, auth_ctx), since)
    items: list[RawItem] = []

    for entry in entries:
        html = fetch_text(entry.link, auth_ctx)
        items.append(
            RawItem(
                source="zhihu",
                author_id=author_id,
                author_name=author_name,
                content_id=content_id_from_url(entry.link),
                content_type=detect_content_type(entry.link),
                title=entry.title,
                url=entry.link,
                published_at=entry.published_at,
                updated_at=entry.updated_at,
                summary=entry.summary,
                raw_html=html,
                tags=entry.categories,
                metadata={"feed_url": feed_url},
            )
        )
    return items
