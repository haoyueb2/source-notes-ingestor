from __future__ import annotations

import json
import re
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from ..browser_automation import discover_zhihu_profile_urls, fetch_pages_with_browser
from ..html_tools import extract_summary, extract_title
from ..models import RawItem
from ..utils import parse_datetime, slugify
from .feed import fetch_feed_entries, fetch_text, filter_since, load_seed_pages


class ZhihuAccessError(RuntimeError):
    pass


AUTHOR_TOKEN_PATTERNS = [
    re.compile(r'itemprop="url"\s+content="https://www\.zhihu\.com/people/([^"/]+)"'),
    re.compile(r'href="//www\.zhihu\.com/people/([^"/]+)"'),
    re.compile(r'"urlToken":"([^"]+)"'),
]

AUTHOR_NAME_PATTERNS = [
    re.compile(r'data-zop="[^\"]*&quot;authorName&quot;:&quot;([^&]+)&quot;'),
    re.compile(r'itemprop="name"\s+content="([^"]+)"'),
]

ZH_BASE = "https://www.zhihu.com"


def detect_content_type(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if "zhuanlan.zhihu.com" in host or "/p/" in path or "/posts" in path:
        return "article"
    if "/answer/" in path:
        return "answer"
    if "/pin/" in path or "/moments/" in path:
        return "thought"
    return "article"


def content_id_from_url(url: str) -> str:
    segments = [segment for segment in urlparse(url).path.split("/") if segment]
    return segments[-1] if segments else slugify(url)


def _extract_author_token(html: str) -> str | None:
    for pattern in AUTHOR_TOKEN_PATTERNS:
        match = pattern.search(html)
        if match:
            return match.group(1).strip()
    return None


def _extract_author_name(html: str) -> str | None:
    for pattern in AUTHOR_NAME_PATTERNS:
        match = pattern.search(html)
        if match:
            return match.group(1).strip()
    return None


def _matches_target_author(html: str, author_id: str, author_name: str) -> bool:
    extracted_token = _extract_author_token(html)
    if extracted_token and extracted_token == author_id:
        return True
    extracted_name = _extract_author_name(html)
    if extracted_name and extracted_name == author_name:
        return True
    return False


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value).strip()


def _cookie_header_from_browser(storage_state_path: str | Path) -> str:
    state = json.loads(Path(storage_state_path).expanduser().read_text(encoding="utf-8"))
    cookies = []
    for cookie in state.get("cookies", []):
        if "zhihu.com" in cookie.get("domain", ""):
            cookies.append(f"{cookie['name']}={cookie['value']}")
    if not cookies:
        raise ZhihuAccessError(f"No Zhihu cookies found in {storage_state_path}")
    return "; ".join(cookies)


def _api_get_json(url: str, cookie_header: str, referer: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Cookie": cookie_header,
            "Referer": referer,
            "X-Requested-With": "fetch",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _api_auth_ctx(cookie_header: str) -> dict[str, str]:
    return {"cookie": cookie_header, "user_agent": "Mozilla/5.0"}


def _api_fetch_all_items(member: str, kind: str, cookie_header: str) -> list[dict]:
    items: list[dict] = []
    next_url = f"{ZH_BASE}/api/v4/members/{member}/{kind}?limit=20&offset=0"
    while next_url:
        payload = _api_get_json(next_url, cookie_header, referer=f"{ZH_BASE}/people/{member}")
        items.extend(payload.get("data", []))
        paging = payload.get("paging", {})
        if paging.get("is_end"):
            break
        next_url = paging.get("next")
        if next_url and next_url.startswith("http://"):
            next_url = "https://" + next_url[len("http://") :]
    return items


def _answer_detail(answer_id: str, cookie_header: str, member: str) -> dict:
    url = f"{ZH_BASE}/api/v4/answers/{answer_id}?include=content,created_time,updated_time,author,question"
    return _api_get_json(url, cookie_header, referer=f"{ZH_BASE}/people/{member}/answers")


def _raw_from_answer(detail: dict, author_id: str, author_name: str) -> RawItem | None:
    author = detail.get("author") or {}
    if author.get("url_token") != author_id:
        return None
    question = detail.get("question") or {}
    answer_id = str(detail.get("id"))
    qid = question.get("id")
    url = f"{ZH_BASE}/question/{qid}/answer/{answer_id}"
    title = f"{question.get('title', answer_id)} - {author.get('name', author_name)} 的回答"
    content = detail.get("content") or ""
    return RawItem(
        source="zhihu",
        author_id=author_id,
        author_name=author_name,
        content_id=answer_id,
        content_type="answer",
        title=title,
        url=url,
        published_at=datetime.fromtimestamp(detail.get("created_time"), tz=UTC) if detail.get("created_time") else None,
        updated_at=datetime.fromtimestamp(detail.get("updated_time"), tz=UTC) if detail.get("updated_time") else None,
        summary=_strip_html(content)[:240],
        raw_html=f"<article>{content}</article>",
        tags=[],
        metadata={"source": "zhihu_api", "question_id": str(qid)},
    )


def _raw_from_article(item: dict, cookie_header: str, author_id: str, author_name: str) -> RawItem | None:
    author = item.get("author") or {}
    if author.get("url_token") != author_id:
        return None
    page_url = (item.get("url") or "").replace("http://", "https://")
    html = fetch_text(page_url, _api_auth_ctx(cookie_header))
    return RawItem(
        source="zhihu",
        author_id=author_id,
        author_name=author_name,
        content_id=str(item.get("id")),
        content_type="article",
        title=item.get("title") or str(item.get("id")),
        url=page_url,
        published_at=datetime.fromtimestamp(item.get("created"), tz=UTC) if item.get("created") else None,
        updated_at=datetime.fromtimestamp(item.get("updated"), tz=UTC) if item.get("updated") else None,
        summary=_strip_html(item.get("excerpt") or "")[:240],
        raw_html=html,
        tags=[],
        metadata={"source": "zhihu_api"},
    )


def _raw_from_pin(item: dict, author_id: str, author_name: str) -> RawItem | None:
    author = item.get("author") or {}
    if author.get("url_token") != author_id:
        return None
    pin_id = str(item.get("id"))
    content_parts = item.get("content") or []
    html_body = "".join(part.get("content", "") for part in content_parts if isinstance(part, dict))
    url = item.get("url") or f"/pins/{pin_id}"
    if url.startswith("/"):
        url = ZH_BASE + url
    return RawItem(
        source="zhihu",
        author_id=author_id,
        author_name=author_name,
        content_id=pin_id,
        content_type="thought",
        title=item.get("excerpt_title") or pin_id,
        url=url,
        published_at=datetime.fromtimestamp(item.get("created"), tz=UTC) if item.get("created") else None,
        updated_at=datetime.fromtimestamp(item.get("updated"), tz=UTC) if item.get("updated") else None,
        summary=_strip_html(html_body)[:240],
        raw_html=f"<article>{html_body}</article>",
        tags=[tag.get("name", "") for tag in item.get("tags", []) if isinstance(tag, dict) and tag.get("name")],
        metadata={"source": "zhihu_api"},
    )


def _api_raw_items(author_id: str, author_name: str, browser_cfg: dict) -> list[RawItem]:
    storage_state = browser_cfg.get("storage_state")
    if not storage_state:
        raise ZhihuAccessError("Zhihu API ingestion requires `browser.storage_state`.")
    cookie_header = _cookie_header_from_browser(storage_state)

    items: list[RawItem] = []
    for answer in _api_fetch_all_items(author_id, "answers", cookie_header):
        detail = _answer_detail(str(answer.get("id")), cookie_header, author_id)
        raw = _raw_from_answer(detail, author_id, author_name)
        if raw is not None:
            items.append(raw)

    for article in _api_fetch_all_items(author_id, "articles", cookie_header):
        raw = _raw_from_article(article, cookie_header, author_id, author_name)
        if raw is not None:
            items.append(raw)

    for pin in _api_fetch_all_items(author_id, "pins", cookie_header):
        raw = _raw_from_pin(pin, author_id, author_name)
        if raw is not None:
            items.append(raw)
    return items


def _raw_item_from_page(url: str, html: str, author_id: str, author_name: str) -> RawItem | None:
    if "知乎 - 有问题，就会有答案" in html and "403" in html:
        raise ZhihuAccessError("Zhihu blocked the page with a 403 challenge. Provide login cookies, browser auth, or saved HTML.")
    if not _matches_target_author(html, author_id, author_name):
        return None
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


def _browser_seed_pages(target: dict) -> list[tuple[str, str]]:
    browser_cfg = target.get("browser") or {}
    if not browser_cfg.get("enabled"):
        return []
    storage_state = browser_cfg.get("storage_state")
    if not storage_state:
        raise ZhihuAccessError("Zhihu browser automation requires `browser.storage_state`.")

    page_urls = list(target.get("page_urls", []))
    profile_url = target.get("profile_url") or target.get("author_url")
    if profile_url:
        discovered = discover_zhihu_profile_urls(
            profile_url,
            storage_state,
            browser_channel=browser_cfg.get("channel", "chrome"),
            headless=browser_cfg.get("headless", True),
            scroll_steps=browser_cfg.get("scroll_steps", 8),
            delay_ms=browser_cfg.get("delay_ms", 900),
            max_items=browser_cfg.get("max_items", 60),
            user_data_dir=browser_cfg.get("user_data_dir"),
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
        user_data_dir=browser_cfg.get("user_data_dir"),
    )
    return [(page.url, page.html) for page in browser_pages]


def _materialize_pages(pages: list[tuple[str, str]], author_id: str, author_name: str) -> list[RawItem]:
    items: list[RawItem] = []
    for url, html in pages:
        item = _raw_item_from_page(url, html, author_id, author_name)
        if item is not None:
            items.append(item)
    return items


def _dedupe_items(items: list[RawItem]) -> list[RawItem]:
    deduped: list[RawItem] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (item.content_type, item.content_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def fetch_source(target: dict, auth_ctx: dict | None, since: datetime | None) -> list[RawItem]:
    author_id = target.get("author_id") or slugify(target.get("author_name", "zhihu-author"))
    author_name = target.get("author_name") or author_id
    browser_cfg = target.get("browser") or {}

    if browser_cfg.get("enabled") and browser_cfg.get("storage_state") and browser_cfg.get("use_api", True):
        return _dedupe_items(_api_raw_items(author_id, author_name, browser_cfg))

    seed_pages = load_seed_pages(target, auth_ctx)
    if seed_pages:
        return _dedupe_items(_materialize_pages([(page.url, page.html) for page in seed_pages], author_id, author_name))

    browser_pages = _browser_seed_pages(target)
    if browser_pages:
        return _dedupe_items(_materialize_pages(browser_pages, author_id, author_name))

    feed_url = target["feed_url"]
    entries = filter_since(fetch_feed_entries(feed_url, auth_ctx), since)
    items: list[RawItem] = []

    for entry in entries:
        html = fetch_text(entry.link, auth_ctx)
        item = _raw_item_from_page(entry.link, html, author_id, author_name)
        if item is None:
            continue
        item.published_at = entry.published_at
        item.updated_at = entry.updated_at
        item.summary = entry.summary or item.summary
        item.tags = entry.categories
        item.metadata = {"feed_url": feed_url}
        items.append(item)
    return _dedupe_items(items)
