from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .utils import ensure_dir, slugify


class BrowserAutomationError(RuntimeError):
    pass


@dataclass(slots=True)
class BrowserPage:
    url: str
    html: str


@dataclass(slots=True)
class BrowserAuthResult:
    source: str
    storage_state_path: str
    login_url: str


def _load_playwright():
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserAutomationError(
            "Playwright is not installed. Run `python3 -m pip install playwright` and then `python3 -m playwright install chromium`."
        ) from exc
    return sync_playwright, PlaywrightTimeoutError


def default_storage_state_path(base_dir: str | Path, source: str) -> Path:
    return Path(base_dir).expanduser() / "browser" / f"{source}.json"


def save_login_session(source: str, login_url: str, storage_state_path: str | Path, browser_channel: str = "chrome") -> BrowserAuthResult:
    sync_playwright, _ = _load_playwright()
    storage_state = Path(storage_state_path).expanduser()
    ensure_dir(storage_state.parent)

    with sync_playwright() as playwright:
        browser_launcher = playwright.chromium
        browser = browser_launcher.launch(channel=browser_channel, headless=False)
        context = browser.new_context(storage_state=str(storage_state) if storage_state.exists() else None)
        page = context.new_page()
        page.goto(login_url, wait_until="domcontentloaded")
        print(
            f"Complete login/verification for {source} in the opened browser, then press Enter here to save the session.",
            file=sys.stderr,
        )
        input()
        context.storage_state(path=str(storage_state))
        context.close()
        browser.close()

    return BrowserAuthResult(source=source, storage_state_path=str(storage_state), login_url=login_url)


def _new_context(playwright, storage_state_path: str | Path | None, browser_channel: str, headless: bool):
    browser = playwright.chromium.launch(channel=browser_channel, headless=headless)
    context = browser.new_context(storage_state=str(storage_state_path) if storage_state_path else None)
    return browser, context


def _scroll_page(page, steps: int, delay_ms: int) -> None:
    for _ in range(max(steps, 0)):
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(delay_ms)


def _extract_links_from_html(html: str, base_url: str, patterns: list[re.Pattern[str]]) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        full = urljoin(base_url, anchor["href"])
        if any(pattern.search(full) for pattern in patterns):
            links.append(full)
    deduped: list[str] = []
    seen: set[str] = set()
    for link in links:
        if link not in seen:
            seen.add(link)
            deduped.append(link)
    return deduped


def fetch_pages_with_browser(
    urls: list[str],
    storage_state_path: str | Path,
    *,
    browser_channel: str = "chrome",
    headless: bool = True,
    scroll_steps: int = 2,
    delay_ms: int = 800,
) -> list[BrowserPage]:
    sync_playwright, PlaywrightTimeoutError = _load_playwright()
    storage_state = Path(storage_state_path).expanduser()
    if not storage_state.exists():
        raise BrowserAutomationError(f"Browser storage state not found: {storage_state}")

    pages: list[BrowserPage] = []
    with sync_playwright() as playwright:
        browser, context = _new_context(playwright, storage_state, browser_channel, headless)
        try:
            for url in urls:
                page = context.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    _scroll_page(page, scroll_steps, delay_ms)
                    pages.append(BrowserPage(url=page.url, html=page.content()))
                except PlaywrightTimeoutError as exc:
                    raise BrowserAutomationError(f"Timed out while loading {url}") from exc
                finally:
                    page.close()
        finally:
            context.close()
            browser.close()
    return pages


def discover_zhihu_profile_urls(
    profile_url: str,
    storage_state_path: str | Path,
    *,
    browser_channel: str = "chrome",
    headless: bool = True,
    scroll_steps: int = 8,
    delay_ms: int = 900,
    max_items: int = 60,
) -> list[str]:
    sync_playwright, PlaywrightTimeoutError = _load_playwright()
    storage_state = Path(storage_state_path).expanduser()
    if not storage_state.exists():
        raise BrowserAutomationError(f"Browser storage state not found: {storage_state}")

    profile_url = profile_url.rstrip("/")
    sections = [
        profile_url,
        f"{profile_url}/answers",
        f"{profile_url}/posts",
        f"{profile_url}/pins",
    ]
    patterns = [
        re.compile(r"zhihu\.com/question/.+/answer/"),
        re.compile(r"zhuanlan\.zhihu\.com/p/"),
        re.compile(r"zhihu\.com/pin/"),
        re.compile(r"zhihu\.com/moments/"),
    ]

    discovered: list[str] = []
    seen: set[str] = set()
    with sync_playwright() as playwright:
        browser, context = _new_context(playwright, storage_state, browser_channel, headless)
        try:
            page = context.new_page()
            try:
                for section in sections:
                    page.goto(section, wait_until="domcontentloaded", timeout=45000)
                    _scroll_page(page, scroll_steps, delay_ms)
                    html = page.content()
                    for link in _extract_links_from_html(html, page.url, patterns):
                        if link not in seen:
                            seen.add(link)
                            discovered.append(link)
                            if len(discovered) >= max_items:
                                return discovered
            except PlaywrightTimeoutError as exc:
                raise BrowserAutomationError(f"Timed out while scanning Zhihu profile {profile_url}") from exc
            finally:
                page.close()
        finally:
            context.close()
            browser.close()
    return discovered


def discover_wechat_article_urls(
    seed_urls: list[str],
    storage_state_path: str | Path,
    *,
    browser_channel: str = "chrome",
    headless: bool = True,
    scroll_steps: int = 2,
    delay_ms: int = 800,
    max_items: int = 30,
) -> list[str]:
    patterns = [re.compile(r"https://mp\.weixin\.qq\.com/s/")]
    pages = fetch_pages_with_browser(
        seed_urls,
        storage_state_path,
        browser_channel=browser_channel,
        headless=headless,
        scroll_steps=scroll_steps,
        delay_ms=delay_ms,
    )
    discovered: list[str] = []
    seen: set[str] = set()
    for browser_page in pages:
        for link in _extract_links_from_html(browser_page.html, browser_page.url, patterns):
            if link not in seen:
                seen.add(link)
                discovered.append(link)
                if len(discovered) >= max_items:
                    return discovered
    return discovered
