from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from ..models import RawItem
from ..utils import slugify
from .feed import fetch_feed_entries, fetch_text, filter_since


def content_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    query = parsed.query.replace("=", "-").replace("&", "-")
    tail = parsed.path.rsplit("/", 1)[-1]
    base = tail or query or url
    return slugify(base)


def fetch_source(target: dict, auth_ctx: dict | None, since: datetime | None) -> list[RawItem]:
    feed_url = target["feed_url"]
    author_id = target.get("account_id") or slugify(target.get("account_name", "wechat-account"))
    author_name = target.get("account_name") or author_id
    entries = filter_since(fetch_feed_entries(feed_url, auth_ctx), since)
    items: list[RawItem] = []

    for entry in entries:
        html = fetch_text(entry.link, auth_ctx)
        items.append(
            RawItem(
                source="wechat",
                author_id=author_id,
                author_name=author_name,
                content_id=content_id_from_url(entry.link),
                content_type="article",
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
