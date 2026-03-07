from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from ..browser_automation import discover_wechat_article_urls, fetch_pages_with_browser
from ..html_tools import extract_summary, extract_title
from ..models import RawItem
from ..utils import slugify
from .feed import fetch_feed_entries, fetch_text, filter_since, load_seed_pages


class WeChatAccessError(RuntimeError):
    pass


def content_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    query = parsed.query.replace("=", "-").replace("&", "-")
    tail = parsed.path.rsplit("/", 1)[-1]
    base = tail or query or url
    return slugify(base)


def _ensure_accessible(html: str) -> None:
    if "环境异常" in html and "完成验证后即可继续访问" in html:
        raise WeChatAccessError("WeChat returned a verification page. Complete the human verification or provide a saved HTML file.")


def _raw_item_from_page(url: str, html: str, author_id: str, author_name: str) -> RawItem:
    _ensure_accessible(html)
    return RawItem(
        source="wechat",
        author_id=author_id,
        author_name=author_name,
        content_id=content_id_from_url(url),
        content_type="article",
        title=extract_title(html) or content_id_from_url(url),
        url=url,
        published_at=None,
        updated_at=None,
        summary=extract_summary(html) or "",
        raw_html=html,
        tags=[],
        metadata={"seed_mode": "page_urls"},
    )


def _browser_seed_pages(target: dict) -> list[tuple[str, str]]:
    browser_cfg = target.get("browser") or {}
    if not browser_cfg.get("enabled"):
        return []
    storage_state = browser_cfg.get("storage_state")
    if not storage_state:
        raise WeChatAccessError("WeChat browser automation requires `browser.storage_state`.")

    page_urls = list(target.get("page_urls", []))
    if browser_cfg.get("discover_from_seed", True) and page_urls:
        discovered = discover_wechat_article_urls(
            page_urls,
            storage_state,
            browser_channel=browser_cfg.get("channel", "chrome"),
            headless=browser_cfg.get("headless", True),
            scroll_steps=browser_cfg.get("scroll_steps", 2),
            delay_ms=browser_cfg.get("delay_ms", 800),
            max_items=browser_cfg.get("max_items", 30),
        )
        page_urls.extend(discovered)

    if not page_urls:
        return []

    browser_pages = fetch_pages_with_browser(
        page_urls,
        storage_state,
        browser_channel=browser_cfg.get("channel", "chrome"),
        headless=browser_cfg.get("headless", True),
        scroll_steps=browser_cfg.get("scroll_steps", 2),
        delay_ms=browser_cfg.get("delay_ms", 800),
    )
    return [(page.url, page.html) for page in browser_pages]


def fetch_source(target: dict, auth_ctx: dict | None, since: datetime | None) -> list[RawItem]:
    author_id = target.get("account_id") or slugify(target.get("account_name", "wechat-account"))
    author_name = target.get("account_name") or author_id

    seed_pages = load_seed_pages(target, auth_ctx)
    if seed_pages:
        return [_raw_item_from_page(page.url, page.html, author_id, author_name) for page in seed_pages]

    browser_pages = _browser_seed_pages(target)
    if browser_pages:
        return [_raw_item_from_page(url, html, author_id, author_name) for url, html in browser_pages]

    feed_url = target["feed_url"]
    entries = filter_since(fetch_feed_entries(feed_url, auth_ctx), since)
    items: list[RawItem] = []

    for entry in entries:
        html = fetch_text(entry.link, auth_ctx)
        _ensure_accessible(html)
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
