from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from playwright.sync_api import sync_playwright

from .utils import ensure_dir


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
    vault_counts: dict[str, int]
    checks: dict[str, CountCheck]


def _count_markdown(vault_root: Path, author_id: str) -> dict[str, int]:
    base = vault_root / 'Sources' / 'Zhihu' / author_id
    return {
        'answers': len(list((base / 'answers').glob('*.md'))) if (base / 'answers').exists() else 0,
        'articles': len(list((base / 'articles').glob('*.md'))) if (base / 'articles').exists() else 0,
        'thoughts': len(list((base / 'thoughts').glob('*.md'))) if (base / 'thoughts').exists() else 0,
    }


def _scrape_counts(profile_url: str, user_data_dir: str | Path) -> tuple[dict[str, int], dict[str, int]]:
    profile_dir = Path(user_data_dir).expanduser()
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(profile_dir),
            channel='chrome',
            headless=False,
            args=['--disable-blink-features=AutomationControlled', '--disable-features=IsolateOrigins,site-per-process'],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(profile_url, wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(4000)
        profile_counts = page.evaluate(
            r'''() => {
                const text = document.body.innerText;
                const out = {answers: 0, articles: 0, thoughts: 0};
                const patterns = [
                  ['answers', /回答\s+(\d+)/],
                  ['articles', /文章\s+(\d+)/],
                  ['thoughts', /想法\s+(\d+)/],
                ];
                for (const [key, pattern] of patterns) {
                  const m = text.match(pattern);
                  if (m) out[key] = Number(m[1]);
                }
                return out;
            }'''
        )

        accessible_counts = {}
        sections = {
            'answers': f"{profile_url.rstrip('/')}/answers",
            'articles': f"{profile_url.rstrip('/')}/posts",
            'thoughts': f"{profile_url.rstrip('/')}/pins",
        }
        for key, url in sections.items():
            page.goto(url, wait_until='domcontentloaded', timeout=45000)
            page.wait_for_timeout(4000)
            for _ in range(20):
                data = page.evaluate(
                    r'''(kind) => {
                        const sel = kind === 'answers'
                          ? '.ContentItem.AnswerItem[name], [itemtype="http://schema.org/Answer"][name]'
                          : kind === 'articles'
                          ? 'a[href*="zhuanlan.zhihu.com/p/"]'
                          : 'a[href*="/pin/"]';
                        const values = Array.from(document.querySelectorAll(sel)).map(el => kind === 'articles' ? el.href : (el.getAttribute('name') || el.href)).filter(Boolean);
                        return [...new Set(values)].length;
                    }''',
                    key,
                )
                page.mouse.wheel(0, 5000)
                page.wait_for_timeout(1200)
                data2 = page.evaluate(
                    r'''(kind) => {
                        const sel = kind === 'answers'
                          ? '.ContentItem.AnswerItem[name], [itemtype="http://schema.org/Answer"][name]'
                          : kind === 'articles'
                          ? 'a[href*="zhuanlan.zhihu.com/p/"]'
                          : 'a[href*="/pin/"]';
                        const values = Array.from(document.querySelectorAll(sel)).map(el => kind === 'articles' ? el.href : (el.getAttribute('name') || el.href)).filter(Boolean);
                        return [...new Set(values)].length;
                    }''',
                    key,
                )
                if data2 == data:
                    accessible_counts[key] = data2
                    break
            else:
                accessible_counts[key] = data2
        context.close()
    return profile_counts, accessible_counts


def verify_zhihu_ingestion(profile_url: str, author_id: str, user_data_dir: str | Path, vault_root: str | Path, out_path: str | Path | None = None) -> ZhihuVerificationReport:
    profile_counts, accessible_counts = _scrape_counts(profile_url, user_data_dir)
    vault_counts = _count_markdown(Path(vault_root), author_id)

    checks: dict[str, CountCheck] = {}
    for key in ['answers', 'articles', 'thoughts']:
        expected = accessible_counts.get(key, 0)
        actual = vault_counts.get(key, 0)
        status = 'pass' if expected == actual else 'fail'
        note = ''
        if profile_counts.get(key, 0) != accessible_counts.get(key, 0):
            note = f"profile shows {profile_counts.get(key, 0)} but accessible list exposes {accessible_counts.get(key, 0)}"
        checks[key] = CountCheck(expected=expected, actual=actual, status=status, note=note)

    report = ZhihuVerificationReport(
        author_id=author_id,
        profile_counts=profile_counts,
        accessible_counts=accessible_counts,
        vault_counts=vault_counts,
        checks=checks,
    )

    if out_path is not None:
        path = Path(out_path).expanduser()
        ensure_dir(path.parent)
        path.write_text(json.dumps({
            'author_id': report.author_id,
            'profile_counts': report.profile_counts,
            'accessible_counts': report.accessible_counts,
            'vault_counts': report.vault_counts,
            'checks': {k: asdict(v) for k, v in report.checks.items()},
        }, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
