from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .utils import ensure_dir


COUNT_KEYS = ("answers", "articles", "thoughts")
PROFILE_PATTERNS = {
    "answers": re.compile(r"回答\s*(\d+)"),
    "articles": re.compile(r"文章\s*(\d+)"),
    "thoughts": re.compile(r"想法\s*(\d+)"),
}
SECTION_URLS = {
    "answers": "/answers",
    "articles": "/posts",
    "thoughts": "/pins",
}
ACCESSIBLE_SELECTORS = {
    "answers": """() => [...new Set(
        Array.from(document.querySelectorAll('.ContentItem.AnswerItem[name], [itemtype="http://schema.org/Answer"][name]'))
          .map(el => el.getAttribute('name'))
          .filter(Boolean)
      )].length""",
    "articles": """() => [...new Set(
        Array.from(document.querySelectorAll('a[href*="zhuanlan.zhihu.com/p/"]'))
          .map(anchor => anchor.href)
      )].length""",
}


@dataclass(slots=True)
class CountCheck:
    expected: int
    actual: int
    status: str
    note: str = ""


@dataclass(slots=True)
class ZhihuVerificationReport:
    author_id: str
    profile_counts: dict[str, int]
    accessible_counts: dict[str, int]
    library_counts: dict[str, int]
    checks: dict[str, CountCheck]


def _count_markdown(library_root: Path, author_id: str) -> dict[str, int]:
    base = library_root / "Sources" / "Zhihu" / author_id
    return {
        "answers": len(list((base / "answers").glob("*.md"))) if (base / "answers").exists() else 0,
        "articles": len(list((base / "articles").glob("*.md"))) if (base / "articles").exists() else 0,
        "thoughts": len(list((base / "thoughts").glob("*.md"))) if (base / "thoughts").exists() else 0,
    }


def _profile_text_counts(text: str) -> dict[str, int]:
    counts = {key: 0 for key in COUNT_KEYS}
    for key, pattern in PROFILE_PATTERNS.items():
        match = pattern.search(text)
        if match:
            counts[key] = int(match.group(1))
    return counts


def _copy_profile(user_data_dir: str | Path) -> str:
    source = Path(user_data_dir).expanduser()
    temp_root = Path(tempfile.mkdtemp(prefix="sni-zhihu-verify-"))
    profile_copy = temp_root / "profile"
    shutil.copytree(
        source,
        profile_copy,
        ignore=shutil.ignore_patterns("Singleton*", "lockfile", "Crashpad", "Default/Cache", "Default/Code Cache"),
    )
    return str(profile_copy)


def _scroll_until_stable(page, counter: Callable[[], int], *, max_rounds: int = 40, stable_rounds: int = 3) -> int:
    prev = -1
    stable = 0
    count = 0
    for _ in range(max_rounds):
        count = counter()
        if count == prev:
            stable += 1
        else:
            stable = 0
        if stable >= stable_rounds:
            return count
        prev = count
        page.mouse.wheel(0, 9000)
        page.wait_for_timeout(1500)
    return count


def _browser_fetch_json(page, path: str) -> dict | None:
    payload = page.evaluate(
        """async (path) => {
          const res = await fetch(path, { credentials: 'include' });
          return { status: res.status, text: await res.text() };
        }""",
        path,
    )
    if payload["status"] != 200:
        return None
    return json.loads(payload["text"])


def _scrape_counts(profile_url: str, user_data_dir: str | Path) -> tuple[dict[str, int], dict[str, int]]:
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError("playwright is required for zhihu verification. Install the browser extra first.") from exc

    temp_profile = _copy_profile(user_data_dir)
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                temp_profile,
                channel="chrome",
                headless=False,
                args=["--disable-blink-features=AutomationControlled", "--disable-features=IsolateOrigins,site-per-process"],
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(profile_url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(6000)
                profile_counts = _profile_text_counts(page.locator("body").inner_text())

                accessible_counts: dict[str, int] = {}
                for key in COUNT_KEYS:
                    section_url = f"{profile_url.rstrip('/')}{SECTION_URLS[key]}"
                    page.goto(section_url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(5000)
                    if key == "thoughts":
                        member = profile_url.rstrip("/").split("/")[-1]
                        payload = _browser_fetch_json(page, f"/api/v4/members/{member}/pins?limit=100&offset=0")
                        accessible_counts[key] = len(payload.get("data", [])) if payload is not None else _scroll_until_stable(
                            page,
                            lambda: page.evaluate(
                                """() => [...new Set(
                                    Array.from(document.querySelectorAll('a[href*="/pin/"]'))
                                      .map(anchor => anchor.href)
                                      .filter(href => href.includes('/pin/'))
                                  )].length"""
                            ),
                        )
                        continue
                    accessible_counts[key] = _scroll_until_stable(page, lambda key=key: page.evaluate(ACCESSIBLE_SELECTORS[key]))
            finally:
                context.close()
    finally:
        shutil.rmtree(Path(temp_profile).parent, ignore_errors=True)
    return profile_counts, accessible_counts


def _build_checks(profile_counts: dict[str, int], accessible_counts: dict[str, int], library_counts: dict[str, int]) -> dict[str, CountCheck]:
    checks: dict[str, CountCheck] = {}
    for key in COUNT_KEYS:
        expected = accessible_counts.get(key, 0)
        actual = library_counts.get(key, 0)
        status = "pass" if expected == actual else "fail"
        notes: list[str] = []
        profile_value = profile_counts.get(key, 0)
        if profile_value != expected:
            if expected == actual:
                status = "warn"
            notes.append(f"profile shows {profile_value} but accessible list exposes {expected}")
        checks[key] = CountCheck(expected=expected, actual=actual, status=status, note="; ".join(notes))
    return checks


def verify_zhihu_ingestion(
    profile_url: str,
    author_id: str,
    user_data_dir: str | Path,
    library_root: str | Path,
    out_path: str | Path | None = None,
) -> ZhihuVerificationReport:
    profile_counts, accessible_counts = _scrape_counts(profile_url, user_data_dir)
    library_counts = _count_markdown(Path(library_root), author_id)
    report = ZhihuVerificationReport(
        author_id=author_id,
        profile_counts=profile_counts,
        accessible_counts=accessible_counts,
        library_counts=library_counts,
        checks=_build_checks(profile_counts, accessible_counts, library_counts),
    )

    if out_path is not None:
        path = Path(out_path).expanduser()
        ensure_dir(path.parent)
        path.write_text(
            json.dumps(
                {
                    "author_id": report.author_id,
                    "profile_counts": report.profile_counts,
                    "accessible_counts": report.accessible_counts,
                    "library_counts": report.library_counts,
                    "checks": {key: asdict(value) for key, value in report.checks.items()},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return report
