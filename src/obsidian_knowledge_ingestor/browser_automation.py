from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse
from collections.abc import Iterator

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
    user_data_dir: str


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


def default_user_data_dir(base_dir: str | Path, source: str) -> Path:
    return Path(base_dir).expanduser() / "browser-profile" / source


def _launch_args() -> list[str]:
    return [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
    ]


def _copy_user_data_dir(user_data_dir: str | Path) -> tuple[Path, Path]:
    source = Path(user_data_dir).expanduser()
    temp_root = Path(tempfile.mkdtemp(prefix="oki-browser-profile-"))
    profile_copy = temp_root / "profile"
    shutil.copytree(
        source,
        profile_copy,
        ignore=shutil.ignore_patterns("Singleton*", "lockfile", "Crashpad", "Default/Cache", "Default/Code Cache"),
    )
    return profile_copy, temp_root


def save_login_session(
    source: str,
    login_url: str,
    storage_state_path: str | Path,
    browser_channel: str = "chrome",
    user_data_dir: str | Path | None = None,
) -> BrowserAuthResult:
    sync_playwright, _ = _load_playwright()
    storage_state = Path(storage_state_path).expanduser()
    profile_dir = Path(user_data_dir).expanduser() if user_data_dir else default_user_data_dir(storage_state.parent.parent, source)
    ensure_dir(storage_state.parent)
    ensure_dir(profile_dir)

    with sync_playwright() as playwright:
        browser_launcher = playwright.chromium
        context = browser_launcher.launch_persistent_context(
            str(profile_dir),
            channel=browser_channel,
            headless=False,
            args=_launch_args(),
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(login_url, wait_until="domcontentloaded")
        print(
            f"Complete login/verification for {source} in the opened browser, then press Enter here to save the session.",
            file=sys.stderr,
        )
        input()
        context.storage_state(path=str(storage_state))
        context.close()

    return BrowserAuthResult(
        source=source,
        storage_state_path=str(storage_state),
        login_url=login_url,
        user_data_dir=str(profile_dir),
    )


def _new_context(
    playwright,
    storage_state_path: str | Path | None,
    browser_channel: str,
    headless: bool,
    user_data_dir: str | Path | None = None,
):
    profile_dir = Path(user_data_dir).expanduser() if user_data_dir else None
    if profile_dir:
        ensure_dir(profile_dir)
        isolated_profile, cleanup_root = _copy_user_data_dir(profile_dir)
        context = playwright.chromium.launch_persistent_context(
            str(isolated_profile),
            channel=browser_channel,
            headless=headless,
            args=_launch_args(),
        )
        return None, context, cleanup_root
    browser = playwright.chromium.launch(channel=browser_channel, headless=headless, args=_launch_args())
    context = browser.new_context(storage_state=str(storage_state_path) if storage_state_path else None)
    return browser, context, None


def _scroll_page(page, steps: int, delay_ms: int) -> None:
    for _ in range(max(steps, 0)):
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(delay_ms)


def _zhihu_challenge(page) -> bool:
    url = page.url or ""
    if "zhihu.com/account/unhuman" in url:
        return True
    title = page.title()
    if "安全验证" in title:
        return True
    text = page.locator("body").inner_text(timeout=3000)
    return "开始验证" in text and "网络环境存在异常" in text


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


def iter_pages_with_browser(
    urls: list[str],
    storage_state_path: str | Path,
    *,
    browser_channel: str = "chrome",
    headless: bool = True,
    scroll_steps: int = 2,
    delay_ms: int = 800,
    user_data_dir: str | Path | None = None,
) -> Iterator[BrowserPage]:
    sync_playwright, PlaywrightTimeoutError = _load_playwright()
    storage_state = Path(storage_state_path).expanduser()
    if not storage_state.exists():
        raise BrowserAutomationError(f"Browser storage state not found: {storage_state}")

    with sync_playwright() as playwright:
        browser, context, cleanup_root = _new_context(playwright, storage_state, browser_channel, headless, user_data_dir=user_data_dir)
        try:
            total = len(urls)
            print(f"[browser] fetch queue size={total}", file=sys.stderr)
            for index, url in enumerate(urls, start=1):
                page = context.new_page()
                try:
                    print(f"[browser] fetch {index}/{total} {url}", file=sys.stderr)
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    if "zhihu.com" in page.url and _zhihu_challenge(page):
                        raise BrowserAutomationError(f"Zhihu challenge required at {page.url}. Complete verification in the persistent browser profile, then retry.")
                    _scroll_page(page, scroll_steps, delay_ms)
                    yield BrowserPage(url=page.url, html=page.content())
                except PlaywrightTimeoutError as exc:
                    raise BrowserAutomationError(f"Timed out while loading {url}") from exc
                finally:
                    page.close()
        finally:
            context.close()
            if browser is not None:
                browser.close()
            if cleanup_root is not None:
                shutil.rmtree(cleanup_root, ignore_errors=True)


def fetch_pages_with_browser(
    urls: list[str],
    storage_state_path: str | Path,
    *,
    browser_channel: str = "chrome",
    headless: bool = True,
    scroll_steps: int = 2,
    delay_ms: int = 800,
    user_data_dir: str | Path | None = None,
) -> list[BrowserPage]:
    return list(
        iter_pages_with_browser(
            urls,
            storage_state_path,
            browser_channel=browser_channel,
            headless=headless,
            scroll_steps=scroll_steps,
            delay_ms=delay_ms,
            user_data_dir=user_data_dir,
        )
    )


def discover_zhihu_profile_urls(
    profile_url: str,
    storage_state_path: str | Path,
    *,
    browser_channel: str = "chrome",
    headless: bool = True,
    scroll_steps: int = 8,
    delay_ms: int = 900,
    max_items: int = 60,
    user_data_dir: str | Path | None = None,
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
        browser, context, cleanup_root = _new_context(playwright, storage_state, browser_channel, headless, user_data_dir=user_data_dir)
        try:
            page = context.new_page()
            try:
                for section in sections:
                    print(f"[browser] discover {section}", file=sys.stderr)
                    page.goto(section, wait_until="domcontentloaded", timeout=45000)
                    if "zhihu.com" in page.url and _zhihu_challenge(page):
                        raise BrowserAutomationError(f"Zhihu challenge required at {page.url}. Complete verification in the persistent browser profile, then retry.")
                    _scroll_page(page, scroll_steps, delay_ms)
                    html = page.content()
                    for link in _extract_links_from_html(html, page.url, patterns):
                        if link not in seen:
                            seen.add(link)
                            discovered.append(link)
                            if len(discovered) % 10 == 0:
                                print(f"[browser] discovered {len(discovered)} urls so far", file=sys.stderr)
                            if len(discovered) >= max_items:
                                return discovered
            except PlaywrightTimeoutError as exc:
                raise BrowserAutomationError(f"Timed out while scanning Zhihu profile {profile_url}") from exc
            finally:
                page.close()
        finally:
            context.close()
            if browser is not None:
                browser.close()
            if cleanup_root is not None:
                shutil.rmtree(cleanup_root, ignore_errors=True)
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
    user_data_dir: str | Path | None = None,
) -> list[str]:
    patterns = [re.compile(r"https://mp\.weixin\.qq\.com/s/")]
    pages = fetch_pages_with_browser(
        seed_urls,
        storage_state_path,
        browser_channel=browser_channel,
        headless=headless,
        scroll_steps=scroll_steps,
        delay_ms=delay_ms,
        user_data_dir=user_data_dir,
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
