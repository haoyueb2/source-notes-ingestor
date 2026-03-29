from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError

from ..utils import parse_datetime

USER_AGENT = "source-notes-ingestor/0.1 (+https://local)"


class FetchError(RuntimeError):
    pass


@dataclass(slots=True)
class FeedEntry:
    title: str
    link: str
    summary: str
    published_at: datetime | None
    updated_at: datetime | None
    categories: list[str]


@dataclass(slots=True)
class SeedPage:
    url: str
    html: str


def _build_request(url: str, auth_ctx: dict[str, str] | None = None) -> urllib.request.Request:
    headers = {"User-Agent": USER_AGENT}
    if auth_ctx:
        if auth_ctx.get("cookie"):
            headers["Cookie"] = auth_ctx["cookie"]
        if auth_ctx.get("user_agent"):
            headers["User-Agent"] = auth_ctx["user_agent"]
    return urllib.request.Request(url, headers=headers)


def fetch_text(url: str, auth_ctx: dict[str, str] | None = None) -> str:
    try:
        with urllib.request.urlopen(_build_request(url, auth_ctx), timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} while fetching {url}") from exc
    except Exception as exc:
        raise FetchError(f"Failed to fetch {url}: {exc}") from exc


def parse_feed(xml_text: str) -> list[FeedEntry]:
    root = ET.fromstring(xml_text)
    entries: list[FeedEntry] = []

    if root.tag.endswith("rss"):
        channel = root.find("channel")
        if channel is None:
            return entries
        for item in channel.findall("item"):
            entries.append(
                FeedEntry(
                    title=(item.findtext("title") or "").strip(),
                    link=(item.findtext("link") or "").strip(),
                    summary=(item.findtext("description") or "").strip(),
                    published_at=parse_datetime(item.findtext("pubDate")),
                    updated_at=parse_datetime(item.findtext("pubDate")),
                    categories=[c.text.strip() for c in item.findall("category") if c.text],
                )
            )
        return entries

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("atom:entry", ns):
        link_el = entry.find("atom:link", ns)
        href = link_el.attrib.get("href", "") if link_el is not None else ""
        entries.append(
            FeedEntry(
                title=(entry.findtext("atom:title", default="", namespaces=ns) or "").strip(),
                link=href.strip(),
                summary=(entry.findtext("atom:summary", default="", namespaces=ns) or "").strip(),
                published_at=parse_datetime(entry.findtext("atom:published", default=None, namespaces=ns)),
                updated_at=parse_datetime(entry.findtext("atom:updated", default=None, namespaces=ns)),
                categories=[c.attrib.get("term", "").strip() for c in entry.findall("atom:category", ns) if c.attrib.get("term")],
            )
        )
    return entries


def fetch_feed_entries(feed_url: str, auth_ctx: dict[str, str] | None = None) -> list[FeedEntry]:
    return parse_feed(fetch_text(feed_url, auth_ctx))


def filter_since(entries: Iterable[FeedEntry], since: datetime | None) -> list[FeedEntry]:
    if since is None:
        return list(entries)
    kept = []
    for entry in entries:
        if entry.updated_at and entry.updated_at > since:
            kept.append(entry)
        elif entry.published_at and entry.published_at > since:
            kept.append(entry)
    return kept


def load_seed_pages(target: dict, auth_ctx: dict[str, str] | None = None) -> list[SeedPage]:
    pages: list[SeedPage] = []
    for url in target.get("page_urls", []):
        pages.append(SeedPage(url=url, html=fetch_text(url, auth_ctx)))
    for path in target.get("html_paths", []):
        html_path = Path(path).expanduser()
        pages.append(SeedPage(url=target.get("base_url") or html_path.as_uri(), html=html_path.read_text(encoding="utf-8")))
    return pages
