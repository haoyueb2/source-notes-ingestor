from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from ..html_tools import extract_summary, extract_title
from ..models import RawItem
from ..utils import slugify
from .feed import fetch_feed_entries, fetch_text, filter_since, load_seed_pages


class ZhihuAccessError(RuntimeError):
    pass


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


def _raw_item_from_page(url: str, html: str, author_id: str, author_name: str) -> RawItem:
    if "知乎 - 有问题，就会有答案" in html and "403" in html:
        raise ZhihuAccessError("Zhihu blocked the page with a 403 challenge. Provide login cookies or saved HTML.")
    return RawItem(
        source="zhihu",
        author_id=author_id,
        author_name=author_name,
        content_id=content_id_from_url(url),
        content_type=detect_content_type(url),
        title=extract_title(html) or content_id_from_url(url),
        url=url,
        published_at=None,
        updated_at=None,
        summary=extract_summary(html) or "",
        raw_html=html,
        tags=[],
        metadata={"seed_mode": "page_urls"},
    )


def fetch_source(target: dict, auth_ctx: dict | None, since: datetime | None) -> list[RawItem]:
    author_id = target.get("author_id") or slugify(target.get("author_name", "zhihu-author"))
    author_name = target.get("author_name") or author_id

    seed_pages = load_seed_pages(target, auth_ctx)
    if seed_pages:
        return [_raw_item_from_page(page.url, page.html, author_id, author_name) for page in seed_pages]

    feed_url = target["feed_url"]
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
