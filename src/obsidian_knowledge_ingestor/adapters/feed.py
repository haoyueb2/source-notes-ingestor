from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable

from ..utils import parse_datetime

USER_AGENT = "obsidian-knowledge-ingestor/0.1 (+https://local)"


@dataclass(slots=True)
class FeedEntry:
    title: str
    link: str
    summary: str
    published_at: object
    updated_at: object
    categories: list[str]


def _build_request(url: str, auth_ctx: dict[str, str] | None = None) -> urllib.request.Request:
    headers = {"User-Agent": USER_AGENT}
    if auth_ctx:
        if auth_ctx.get("cookie"):
            headers["Cookie"] = auth_ctx["cookie"]
        if auth_ctx.get("user_agent"):
            headers["User-Agent"] = auth_ctx["user_agent"]
    return urllib.request.Request(url, headers=headers)


def fetch_text(url: str, auth_ctx: dict[str, str] | None = None) -> str:
    with urllib.request.urlopen(_build_request(url, auth_ctx), timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


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


def filter_since(entries: Iterable[FeedEntry], since) -> list[FeedEntry]:
    if since is None:
        return list(entries)
    kept = []
    for entry in entries:
        if entry.updated_at and entry.updated_at > since:
            kept.append(entry)
        elif entry.published_at and entry.published_at > since:
            kept.append(entry)
    return kept
