from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urljoin


def pick_first(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return html.unescape(match.group(1)).strip()
    return None


class MarkdownExtractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.parts: list[str] = []
        self.assets: list[str] = []
        self.link_stack: list[str] = []
        self.list_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag in {"p", "div", "section", "article"}:
            self.parts.append("\n\n")
        elif tag in {"br"}:
            self.parts.append("\n")
        elif tag in {"h1", "h2", "h3", "h4"}:
            level = min(int(tag[1]), 4)
            self.parts.append(f"\n\n{'#' * level} ")
        elif tag == "li":
            indent = "  " * max(self.list_depth - 1, 0)
            self.parts.append(f"\n{indent}- ")
        elif tag in {"ul", "ol"}:
            self.list_depth += 1
            self.parts.append("\n")
        elif tag == "a":
            href = attr_map.get("href")
            if href:
                self.link_stack.append(urljoin(self.base_url, href))
                self.parts.append("[")
            else:
                self.link_stack.append("")
        elif tag == "img":
            src = attr_map.get("src") or attr_map.get("data-src") or attr_map.get("data-original")
            if src:
                full = urljoin(self.base_url, src)
                self.assets.append(full)
                alt = attr_map.get("alt") or "image"
                self.parts.append(f"\n![{alt}]({full})\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"ul", "ol"} and self.list_depth > 0:
            self.list_depth -= 1
        elif tag == "a" and self.link_stack:
            href = self.link_stack.pop()
            if href:
                self.parts.append(f"]({href})")

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)

    def render(self) -> tuple[str, list[str]]:
        body = "".join(self.parts)
        body = re.sub(r"\n{3,}", "\n\n", body)
        body = re.sub(r"[ \t]+\n", "\n", body)
        return body.strip() + "\n", list(dict.fromkeys(self.assets))


def extract_title(html_text: str) -> str | None:
    return pick_first(
        [
            r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"',
            r'<meta[^>]+name="twitter:title"[^>]+content="([^"]+)"',
            r"<title>(.*?)</title>",
        ],
        html_text,
    )


def extract_summary(html_text: str) -> str | None:
    return pick_first(
        [
            r'<meta[^>]+name="description"[^>]+content="([^"]+)"',
            r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',
        ],
        html_text,
    )


def extract_main_html(html_text: str, source: str) -> str:
    patterns = []
    if source == "wechat":
        patterns.extend([
            r'<div[^>]+id="js_content"[^>]*>(.*?)</div>',
            r'<div[^>]+class="rich_media_content[^"]*"[^>]*>(.*?)</div>',
        ])
    elif source == "zhihu":
        patterns.extend([
            r'<div[^>]+class="RichContent-inner[^"]*"[^>]*>(.*?)</div>',
            r'<article[^>]*>(.*?)</article>',
        ])
    patterns.extend([
        r'<main[^>]*>(.*?)</main>',
        r'<article[^>]*>(.*?)</article>',
        r'<body[^>]*>(.*?)</body>',
    ])

    for pattern in patterns:
        match = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1)
    return html_text


def html_to_markdown(html_text: str, base_url: str) -> tuple[str, list[str]]:
    parser = MarkdownExtractor(base_url)
    parser.feed(html_text)
    return parser.render()
