from __future__ import annotations

import json
import re
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from .browser_automation import BrowserAutomationError, _load_playwright, _new_context
from .utils import ensure_dir

ARTICLE_PATTERNS = [
    re.compile(r"https://mp\.weixin\.qq\.com/s/[A-Za-z0-9_-]+"),
    re.compile(r"https://mp\.weixin\.qq\.com/s\?[^\s\"'<>()]+"),
]
WECHAT_PROFILE_DEFAULT = Path.home() / "Library/Containers/com.tencent.xinWeChat/Data/Documents/app_data/radium/web/profiles"


@dataclass(slots=True)
class DiscoveryReport:
    urls: list[str]
    sources: list[str]
    captcha: str | None = None
    screenshot_path: str | None = None


class WeChatDiscoveryError(RuntimeError):
    pass


def normalize_article_url(url: str) -> str:
    url = url.strip().rstrip('"\'.,;)]}')
    if not url.startswith("https://mp.weixin.qq.com/s?"):
        return url
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("chksm", "scene", "sessionid", "subscene", "clicktime", "enterid", "click_id", "key", "ascene", "uin", "devicetype", "version", "lang", "countrycode", "exportkey", "acctmode", "pass_ticket", "wx_header", "fasttmpl_type", "fasttmpl_fullversion", "from_xworker", "mpshare", "srcid", "sharer_shareinfo", "sharer_shareinfo_first", "nettype", "fontScale", "session_us"):
        query.pop(key, None)
    kept = []
    for k in sorted(query):
        for v in query[k]:
            kept.append(f"{k}={quote(v, safe='')}" )
    return f"https://mp.weixin.qq.com/s?{'&'.join(kept)}" if kept else "https://mp.weixin.qq.com/s"


def _dedupe(urls: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for url in urls:
        normalized = normalize_article_url(url)
        if normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out


def _extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    for pattern in ARTICLE_PATTERNS:
        urls.extend(pattern.findall(text))
    return _dedupe(urls)


def _copy_if_exists(path: Path, temp_dir: Path) -> Path | None:
    if not path.exists():
        return None
    target = temp_dir / path.name
    shutil.copy2(path, target)
    return target


def _sqlite_lines(db_path: Path, sql: str) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(sql).fetchall()
        return ["\t".join("" if cell is None else str(cell) for cell in row) for row in rows]
    finally:
        conn.close()


def _scan_history_db(db_path: Path, account_name: str | None, account_biz: str | None) -> list[str]:
    lines = _sqlite_lines(db_path, "select url, title from urls where url like 'https://mp.weixin.qq.com/%' order by last_visit_time desc")
    urls: list[str] = []
    for line in lines:
        url, _, title = line.partition("\t")
        if not url:
            continue
        if not any(pattern.fullmatch(url) for pattern in ARTICLE_PATTERNS):
            continue
        if account_name and account_name not in title and account_biz and account_biz not in url:
            continue
        urls.append(url)
    return urls


def _scan_share_db(db_path: Path, account_name: str | None, account_biz: str | None) -> list[str]:
    lines = _sqlite_lines(db_path, "select url, real_url, author, share_data from share_data_table")
    urls: list[str] = []
    for line in lines:
        parts = line.split("\t", 3)
        blob = parts[3] if len(parts) == 4 else ""
        candidates = []
        for idx in (0, 1):
            if idx < len(parts) and parts[idx]:
                candidates.extend(_extract_urls(parts[idx]))
        haystack = unquote(blob)
        if account_biz and account_biz not in haystack and account_biz not in "\t".join(parts[:3]):
            continue
        if account_name and account_name not in haystack and account_name not in "\t".join(parts[:3]):
            continue
        candidates.extend(_extract_urls(haystack))
        urls.extend(candidates)
    return urls


def _scan_text_file(path: Path, account_name: str | None, account_biz: str | None) -> list[str]:
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return []
    if account_biz and account_biz not in text and not (account_name and account_name in text):
        return []
    if account_name and account_name not in text and not (account_biz and account_biz in text):
        return []
    return _extract_urls(unquote(text))


def discover_from_local_profile(
    account_name: str,
    *,
    account_biz: str | None = None,
    profile_root: str | Path | None = None,
    limit: int = 500,
) -> DiscoveryReport:
    root = Path(profile_root).expanduser() if profile_root else WECHAT_PROFILE_DEFAULT
    if not root.exists():
        raise WeChatDiscoveryError(f"WeChat local profile root not found: {root}")

    sources: list[str] = []
    urls: list[str] = []

    candidates = [
        root / "multitab_e309f1787e0d9b7476197212293241eb" / "Default",
        root / "multitab_e309f1787e0d9b7476197212293241eb",
        root / "webview_e309f1787e0d9b7476197212293241eb",
    ]
    existing = [path for path in candidates if path.exists()]
    if not existing:
        raise WeChatDiscoveryError(f"No WeChat local profiles found under {root}")

    with tempfile.TemporaryDirectory(prefix="wechat-discovery-") as tmp_dir:
        temp_dir = Path(tmp_dir)
        for base in existing:
            for name in ("History", "History.wxbak", "Share Data"):
                copied = _copy_if_exists(base / name, temp_dir)
                if copied is None:
                    continue
                try:
                    if name.startswith("History"):
                        found = _scan_history_db(copied, account_name, account_biz)
                    else:
                        found = _scan_share_db(copied, account_name, account_biz)
                except sqlite3.DatabaseError:
                    found = []
                if found:
                    sources.append(str(base / name))
                    urls.extend(found)

            for rel in (
                Path("Local Storage/leveldb"),
                Path("IndexedDB/https_mp.weixin.qq.com_0.indexeddb.leveldb"),
                Path("Sessions"),
            ):
                folder = base / rel
                if not folder.exists():
                    continue
                found_here: list[str] = []
                for path in folder.glob("*"):
                    found_here.extend(_scan_text_file(path, account_name, account_biz))
                if found_here:
                    sources.append(str(folder))
                    urls.extend(found_here)

    deduped = _dedupe(urls)
    return DiscoveryReport(urls=deduped[:limit], sources=sources, captcha=None, screenshot_path=None)


def discover_from_sogou(
    query: str,
    *,
    browser_channel: str = "chrome",
    headless: bool = True,
    interactive: bool = False,
    user_data_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> DiscoveryReport:
    sync_playwright, PlaywrightTimeoutError = _load_playwright()
    out_dir = Path(output_dir or Path.cwd() / "output/playwright").expanduser()
    ensure_dir(out_dir)
    search_url = f"https://www.sogou.com/web?query={quote(query + ' site:mp.weixin.qq.com/s')}"

    with sync_playwright() as playwright:
        browser, context = _new_context(playwright, None, browser_channel, headless, user_data_dir=user_data_dir)
        try:
            page = context.new_page()
            try:
                page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
            except PlaywrightTimeoutError as exc:
                raise WeChatDiscoveryError(f"Timed out while searching Sogou for {query}") from exc

            body = page.locator("body").inner_text(timeout=5000)
            is_antispider = "antispider" in page.url or "此验证码用于确认这些请求是您的正常行为而不是自动程序发出的" in body
            if is_antispider:
                screenshot_path = out_dir / "sogou-antispider.png"
                page.screenshot(path=str(screenshot_path), full_page=True)
                if interactive and not headless:
                    print(
                        f"Complete the Sogou verification in the opened browser, then press Enter here to continue. Screenshot: {screenshot_path}",
                        file=sys.stderr,
                    )
                    input()
                    page.wait_for_timeout(2000)
                    body = page.locator("body").inner_text(timeout=5000)
                if "antispider" in page.url or "此验证码用于确认这些请求是您的正常行为而不是自动程序发出的" in body:
                    return DiscoveryReport(urls=[], sources=[search_url], captcha="sogou-antispider", screenshot_path=str(screenshot_path))

            urls = _extract_urls(page.content())
            return DiscoveryReport(urls=urls, sources=[search_url], captcha=None, screenshot_path=None)
        finally:
            context.close()
            if browser is not None:
                browser.close()


def discover_wechat_history(
    account_name: str,
    *,
    account_biz: str | None = None,
    profile_root: str | Path | None = None,
    browser_channel: str = "chrome",
    headless: bool = True,
    user_data_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    min_urls_before_search: int = 5,
) -> DiscoveryReport:
    local_report = discover_from_local_profile(account_name, account_biz=account_biz, profile_root=profile_root)
    if len(local_report.urls) >= min_urls_before_search:
        return local_report

    sogou_report = discover_from_sogou(
        account_name,
        browser_channel=browser_channel,
        headless=headless,
        interactive=not headless,
        user_data_dir=user_data_dir,
        output_dir=output_dir,
    )
    combined_urls = _dedupe(local_report.urls + sogou_report.urls)
    combined_sources = local_report.sources + [source for source in sogou_report.sources if source not in local_report.sources]
    return DiscoveryReport(
        urls=combined_urls,
        sources=combined_sources,
        captcha=sogou_report.captcha,
        screenshot_path=sogou_report.screenshot_path,
    )
