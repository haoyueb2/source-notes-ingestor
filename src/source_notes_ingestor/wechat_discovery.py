from __future__ import annotations

import json
import html
import re
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen

from .browser_automation import _load_playwright, _new_context
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


PROFILE_EXT_REQUIRED_QUERY_KEYS = (
    "__biz",
    "uin",
    "key",
    "pass_ticket",
)


def normalize_article_url(url: str) -> str:
    url = url.strip().rstrip('"\'.,;)]}')
    if url.startswith("http://mp.weixin.qq.com/"):
        url = "https://" + url[len("http://") :]
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


def _dedupe_raw(urls: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
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


def _scan_share_db_rows(db_path: Path, account_name: str | None, account_biz: str | None) -> list[tuple[str, str, str]]:
    lines = _sqlite_lines(db_path, "select url, real_url, author from share_data_table")
    rows: list[tuple[str, str, str]] = []
    for line in lines:
        url, real_url, author = (line.split("\t") + ["", "", ""])[:3]
        haystack = "\t".join((url, real_url, author))
        if account_biz and account_biz not in haystack:
            continue
        if account_name and account_name not in haystack and author != account_name:
            continue
        rows.append((url, real_url, author))
    return rows


def _extract_seed_url_candidates(
    account_name: str,
    *,
    account_biz: str | None = None,
    profile_root: str | Path | None = None,
) -> list[str]:
    root = Path(profile_root).expanduser() if profile_root else WECHAT_PROFILE_DEFAULT
    if not root.exists():
        return []

    candidates = [
        root / "multitab_e309f1787e0d9b7476197212293241eb" / "Default",
        root / "multitab_e309f1787e0d9b7476197212293241eb",
    ]
    existing = [path for path in candidates if path.exists()]
    seed_urls: list[str] = []

    with tempfile.TemporaryDirectory(prefix="wechat-discovery-seeds-") as tmp_dir:
        temp_dir = Path(tmp_dir)
        for base in existing:
            copied = _copy_if_exists(base / "Share Data", temp_dir)
            if copied is None:
                continue
            try:
                rows = _scan_share_db_rows(copied, account_name, account_biz)
            except sqlite3.DatabaseError:
                continue
            for url, real_url, _author in rows:
                if real_url.startswith("https://mp.weixin.qq.com/s?"):
                    seed_urls.append(real_url)
                elif url.startswith("https://mp.weixin.qq.com/s?"):
                    seed_urls.append(url)

    return _dedupe_raw(seed_urls)


def _fetch_text(url: str, *, headers: dict[str, str] | None = None) -> str:
    req = Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def _extract_profile_ext_params(seed_url: str) -> dict[str, str]:
    parsed = urlparse(seed_url)
    query = parse_qs(parsed.query)
    params = {key: query.get(key, [""])[0] for key in PROFILE_EXT_REQUIRED_QUERY_KEYS}
    if not all(params.values()):
        raise WeChatDiscoveryError(f"Seed URL missing required profile_ext params: {seed_url}")
    params["scene"] = query.get("scene", ["126"])[0]
    params["__biz"] = params["__biz"]
    return params


def _extract_appmsg_token(article_html: str) -> str:
    match = re.search(r'appmsg_token\s*=\s*"([^"]+)"', article_html)
    if not match:
        raise WeChatDiscoveryError("Unable to extract appmsg_token from article HTML")
    return match.group(1)


def _extract_urls_from_general_msg_list(payload: dict[str, object]) -> list[str]:
    raw_list = payload.get("general_msg_list")
    if not raw_list:
        return []
    if isinstance(raw_list, str):
        general_msg_list = json.loads(raw_list)
    else:
        general_msg_list = raw_list
    items = general_msg_list.get("list", [])
    urls: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        app_msg = item.get("app_msg_ext_info") or {}
        if isinstance(app_msg, dict):
            content_url = app_msg.get("content_url")
            if isinstance(content_url, str) and content_url:
                urls.append(html.unescape(content_url).replace("#wechat_redirect", ""))
            multi = app_msg.get("multi_app_msg_item_list") or []
            if isinstance(multi, list):
                for sub_item in multi:
                    if not isinstance(sub_item, dict):
                        continue
                    sub_url = sub_item.get("content_url")
                    if isinstance(sub_url, str) and sub_url:
                        urls.append(html.unescape(sub_url).replace("#wechat_redirect", ""))
    return _dedupe(urls)


def discover_from_profile_ext(
    account_name: str,
    *,
    account_biz: str | None = None,
    seed_urls: list[str] | None = None,
    profile_root: str | Path | None = None,
    max_pages: int = 20,
    page_size: int = 10,
) -> DiscoveryReport:
    seeds = _dedupe_raw((seed_urls or []) + _extract_seed_url_candidates(account_name, account_biz=account_biz, profile_root=profile_root))
    if not seeds:
        return DiscoveryReport(urls=[], sources=[], captcha=None, screenshot_path=None)

    all_urls: list[str] = []
    sources: list[str] = []

    for seed in seeds:
        try:
            article_html = _fetch_text(seed)
            params = _extract_profile_ext_params(seed)
            params["appmsg_token"] = _extract_appmsg_token(article_html)
        except Exception:
            continue

        offset = 0
        for _ in range(max_pages):
            query = {
                "action": "getmsg",
                "__biz": params["__biz"],
                "f": "json",
                "offset": str(offset),
                "count": str(page_size),
                "is_ok": "1",
                "scene": params["scene"],
                "uin": params["uin"],
                "key": params["key"],
                "pass_ticket": params["pass_ticket"],
                "appmsg_token": params["appmsg_token"],
                "x5": "1",
            }
            url = f"https://mp.weixin.qq.com/mp/profile_ext?{urlencode(query)}"
            try:
                response_text = _fetch_text(url, headers={"User-Agent": "Mozilla/5.0", "Referer": seed})
                payload = json.loads(response_text)
            except Exception:
                break

            if payload.get("ret") != 0:
                break

            batch_urls = _extract_urls_from_general_msg_list(payload)
            if batch_urls:
                all_urls.extend(batch_urls)
                sources.append(seed)

            if int(payload.get("can_msg_continue") or 0) != 1:
                break
            next_offset = payload.get("next_offset")
            if next_offset is None or str(next_offset) == str(offset):
                break
            offset = int(next_offset)

        if all_urls:
            break

    return DiscoveryReport(urls=_dedupe(all_urls), sources=_dedupe_raw(sources), captcha=None, screenshot_path=None)

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
    seed_urls: list[str] | None = None,
    profile_root: str | Path | None = None,
    browser_channel: str = "chrome",
    headless: bool = True,
    user_data_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    min_urls_before_search: int = 5,
) -> DiscoveryReport:
    profile_ext_report = discover_from_profile_ext(
        account_name,
        account_biz=account_biz,
        seed_urls=seed_urls,
        profile_root=profile_root,
    )
    if len(profile_ext_report.urls) >= min_urls_before_search:
        return DiscoveryReport(
            urls=profile_ext_report.urls,
            sources=profile_ext_report.sources,
            captcha=None,
            screenshot_path=None,
        )

    sogou_report = discover_from_sogou(
        account_name,
        browser_channel=browser_channel,
        headless=headless,
        interactive=not headless,
        user_data_dir=user_data_dir,
        output_dir=output_dir,
    )
    combined_urls = _dedupe(profile_ext_report.urls + sogou_report.urls)
    combined_sources = profile_ext_report.sources + [source for source in sogou_report.sources if source not in profile_ext_report.sources]
    return DiscoveryReport(
        urls=combined_urls,
        sources=combined_sources,
        captcha=sogou_report.captcha,
        screenshot_path=sogou_report.screenshot_path,
    )
