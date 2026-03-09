from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from .browser_automation import BrowserAutomationError, default_storage_state_path, default_user_data_dir, save_login_session
from .qa_builder import CodexUnavailableError, build_scope_package
from .config import AppConfig, load_target
from .pipeline import IngestReport, ingest_source
from .qa_runner import (
    CodexCliUnavailableError,
    ObsidianCliUnavailableError,
    ask_scope,
    ask_scope_as_json,
    open_derived_note,
    read_note,
    search,
    search_scope,
)
from .wechat_discovery import WeChatDiscoveryError, discover_wechat_history
from .utils import dump_json, load_json, slugify
from .adapters.wechat import content_id_from_url


DEFAULT_LOGIN_URLS = {
    "zhihu": "https://www.zhihu.com/signin",
    "wechat": "https://mp.weixin.qq.com/",
}

WECHAT_VERIFICATION_MARKERS = (
    "WeChat returned a verification page",
    "Complete the human verification",
)
WECHAT_DISABLE_RETRY_ENV = "OKI_WECHAT_DISABLE_RETRY"


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return text
    return parts[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oki", description="Obsidian knowledge ingestion CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth_parser = subparsers.add_parser("auth", help="Save a browser login session for a source")
    auth_parser.add_argument("source", choices=["zhihu", "wechat"])
    auth_parser.add_argument("--login-url", help="Override the login or verification URL")
    auth_parser.add_argument("--storage-state", help="Path to the browser storage state JSON")
    auth_parser.add_argument("--user-data-dir", help="Path to a persistent browser profile directory")
    auth_parser.add_argument("--channel", default="chrome", help="Playwright browser channel to use")

    ingest_parser = subparsers.add_parser("ingest", help="Ingest content from a supported source")
    ingest_parser.add_argument("source", choices=["zhihu", "wechat"])
    ingest_parser.add_argument("--target", required=True, help="Path to source target JSON")
    ingest_parser.add_argument("--vault", help="Override Obsidian vault path")

    verify_parser = subparsers.add_parser("verify", help="Verify ingestion counts against source-visible counts")
    verify_parser.add_argument("source", choices=["zhihu"])
    verify_parser.add_argument("--target", required=True, help="Path to source target JSON")
    verify_parser.add_argument("--vault", help="Override Obsidian vault path")
    verify_parser.add_argument("--out", help="Optional JSON report output path")

    discover_parser = subparsers.add_parser("discover", help="Discover source URLs without ingesting content")
    discover_parser.add_argument("source", choices=["wechat"])
    discover_parser.add_argument("--target", required=True, help="Path to source target JSON")
    discover_parser.add_argument("--output-dir", help="Directory for screenshots and debug artifacts")

    search_parser = subparsers.add_parser("search", help="Search the Obsidian vault via official CLI")
    search_parser.add_argument("query")
    search_parser.add_argument("--vault")

    read_parser = subparsers.add_parser("read", help="Read a vault note via official CLI")
    read_parser.add_argument("path")
    read_parser.add_argument("--vault")
    read_parser.add_argument("--body-only", action="store_true")

    build_qa_parser = subparsers.add_parser("build-qa", help="Build a derived QA package for a scope")
    build_qa_parser.add_argument("--scope", required=True)
    build_qa_parser.add_argument("--vault")
    build_qa_parser.add_argument("--rebuild", action="store_true")

    qa_search_parser = subparsers.add_parser("qa-search", help="Search raw scope notes through the official Obsidian CLI")
    qa_search_parser.add_argument("--scope", required=True)
    qa_search_parser.add_argument("--query", required=True)
    qa_search_parser.add_argument("--vault")
    qa_search_parser.add_argument("--limit", type=int, default=8)

    qa_read_parser = subparsers.add_parser("qa-read", help="Read a note path through the official Obsidian CLI")
    qa_read_parser.add_argument("--path", required=True)
    qa_read_parser.add_argument("--vault")
    qa_read_parser.add_argument("--body-only", action="store_true")

    qa_open_parser = subparsers.add_parser("qa-open-derived", help="Read a derived scope note through the official Obsidian CLI")
    qa_open_parser.add_argument("--scope", required=True)
    qa_open_parser.add_argument("--kind", required=True, choices=["overview", "themes", "corpus_index", "full_context", "manifest"])
    qa_open_parser.add_argument("--vault")
    qa_open_parser.add_argument("--body-only", action="store_true")

    ask_parser = subparsers.add_parser("ask", help="Run agentic Q&A against a scope")
    ask_parser.add_argument("prompt")
    ask_parser.add_argument("--scope", required=True)
    ask_parser.add_argument("--context-mode", choices=["map", "fulltext"], default="map")
    ask_parser.add_argument("--agent", choices=["codex", "none"], default="codex")
    ask_parser.add_argument("--json", action="store_true")
    ask_parser.add_argument("--vault")

    return parser


def _wechat_state_path(target: dict, config: AppConfig) -> Path:
    name = target.get("account_name") or target.get("account_id") or "wechat"
    return config.vault_path / config.sync_state_dir_name / f"wechat-{slugify(name)}.json"


def _write_wechat_resume_target(target: dict, config: AppConfig) -> Path:
    state = load_json(_wechat_state_path(target, config))
    done = set((state.get("items") or {}).keys())
    remaining = [url for url in target.get("page_urls", []) if content_id_from_url(url) not in done]
    resume_target = {**target, "page_urls": remaining}
    out_path = config.state_dir / "resume" / f"wechat-{slugify(target.get('account_name', 'wechat'))}-resume.json"
    dump_json(out_path, resume_target)
    return out_path


def _should_retry_wechat_verification(exc: RuntimeError) -> bool:
    message = str(exc)
    return any(marker in message for marker in WECHAT_VERIFICATION_MARKERS)


def _ingest_wechat_with_verification_resume(target_path: str | Path, config: AppConfig) -> IngestReport:
    target = load_target(target_path)
    browser_cfg = target.get("browser") or {}
    retry_delay = int(browser_cfg.get("verification_retry_delay_sec", 20))
    max_retries = int(browser_cfg.get("verification_max_retries", 20))
    attempt = 0
    current_target_path = Path(target_path)
    aggregate = IngestReport(
        source="wechat",
        target_name=target.get("account_name") or target.get("account_id") or "wechat",
        fetched=0,
        written=0,
        skipped=0,
        note_paths=[],
    )

    while True:
        try:
            if attempt == 0:
                report = ingest_source("wechat", current_target_path, config=config)
            else:
                cmd = [sys.executable, "-m", "obsidian_knowledge_ingestor.cli", "ingest", "wechat", "--target", str(current_target_path)]
                env = os.environ.copy()
                env[WECHAT_DISABLE_RETRY_ENV] = "1"
                env["OBSIDIAN_VAULT_PATH"] = str(config.vault_path)
                if "PYTHONPATH" not in env:
                    env["PYTHONPATH"] = "src"
                result = subprocess.run(cmd, cwd=Path(__file__).resolve().parents[2], env=env, capture_output=True, text=True)
                if result.stdout:
                    print(result.stdout, end="")
                if result.stderr:
                    print(result.stderr, file=sys.stderr, end="")
                if result.returncode != 0:
                    raise RuntimeError((result.stderr or result.stdout).strip() or f"WeChat ingest child exited with {result.returncode}")
                report = IngestReport(**json.loads(result.stdout))
            aggregate.fetched += report.fetched
            aggregate.written += report.written
            aggregate.skipped += report.skipped
            aggregate.note_paths.extend(report.note_paths)
            return aggregate
        except RuntimeError as exc:
            if not _should_retry_wechat_verification(exc):
                raise
            attempt += 1
            if attempt > max_retries:
                raise RuntimeError(f"{exc} Retry budget exhausted after {max_retries} attempts.") from exc
            resume_target_path = _write_wechat_resume_target(target, config)
            resume_target = load_target(resume_target_path)
            remaining = len(resume_target.get("page_urls", []))
            if remaining == 0:
                return aggregate
            print(
                f"[wechat] verification wall hit; retry {attempt}/{max_retries} in {retry_delay}s with {remaining} urls remaining",
                file=sys.stderr,
            )
            time.sleep(retry_delay)
            current_target_path = resume_target_path


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = AppConfig.from_env()
    if getattr(args, "vault", None):
        config.vault_path = Path(args.vault).expanduser()

    if args.command == "auth":
        storage_state = args.storage_state or str(default_storage_state_path(config.state_dir, args.source))
        user_data_dir = args.user_data_dir or str(default_user_data_dir(config.state_dir, args.source))
        login_url = args.login_url or DEFAULT_LOGIN_URLS[args.source]
        try:
            result = save_login_session(
                args.source,
                login_url,
                storage_state,
                browser_channel=args.channel,
                user_data_dir=user_data_dir,
            )
        except BrowserAutomationError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0

    if args.command == "verify":
        from .verification import verify_zhihu_ingestion

        target = load_target(args.target)
        author_id = target.get('author_id') or target.get('author_name')
        profile_url = target.get('profile_url') or target.get('author_url') or f"https://www.zhihu.com/people/{author_id}"
        browser_cfg = target.get('browser') or {}
        report = verify_zhihu_ingestion(
            profile_url=profile_url,
            author_id=author_id,
            user_data_dir=browser_cfg.get('user_data_dir'),
            vault_root=args.vault or config.vault_path,
            out_path=args.out,
        )
        from dataclasses import asdict as _asdict
        print(json.dumps({
            'author_id': report.author_id,
            'profile_counts': report.profile_counts,
            'accessible_counts': report.accessible_counts,
            'vault_counts': report.vault_counts,
            'checks': {k: _asdict(v) for k, v in report.checks.items()},
        }, ensure_ascii=False, indent=2))
        return 0

    if args.command == "ingest":
        try:
            if args.source == "wechat" and os.environ.get(WECHAT_DISABLE_RETRY_ENV) != "1":
                report = _ingest_wechat_with_verification_resume(args.target, config=config)
            else:
                report = ingest_source(args.source, args.target, config=config)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
        return 0

    if args.command == "discover":
        if args.source != "wechat":
            print(f"Unsupported discover source: {args.source}", file=sys.stderr)
            return 1
        target = json.loads(Path(args.target).read_text())
        browser_cfg = target.get("browser") or {}
        try:
            report = discover_wechat_history(
                target.get("account_name", "wechat-account"),
                account_biz=target.get("account_biz"),
                seed_urls=target.get("page_urls"),
                browser_channel=browser_cfg.get("channel", "chrome"),
                headless=browser_cfg.get("headless", True),
                user_data_dir=browser_cfg.get("user_data_dir"),
                output_dir=args.output_dir,
            )
        except WeChatDiscoveryError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
        return 0

    if args.command == "build-qa":
        try:
            manifest = build_scope_package(args.scope, config.vault_path, rebuild=args.rebuild)
        except (RuntimeError, CodexUnavailableError, FileNotFoundError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(asdict(manifest), ensure_ascii=False, indent=2))
        return 0

    try:
        if args.command == "search":
            result = search(args.query, vault=args.vault, cwd=config.vault_path)
            print(result.stdout, end="")
            return result.returncode
        if args.command == "read":
            result = read_note(args.path, vault=args.vault, cwd=config.vault_path)
            print(_strip_frontmatter(result.stdout) if args.body_only else result.stdout, end="")
            return result.returncode
        if args.command == "qa-search":
            result = search_scope(args.scope, args.query, config.vault_path, limit=args.limit)
            print(json.dumps([asdict(item) for item in result], ensure_ascii=False, indent=2))
            return 0
        if args.command == "qa-read":
            result = read_note(args.path, vault=args.vault, cwd=config.vault_path)
            if result.stdout:
                print(_strip_frontmatter(result.stdout) if args.body_only else result.stdout, end="")
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="")
            return result.returncode
        if args.command == "qa-open-derived":
            result = open_derived_note(args.kind, args.scope, config.vault_path)
            if result.stdout:
                print(_strip_frontmatter(result.stdout) if args.body_only else result.stdout, end="")
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="")
            return result.returncode
        if args.command == "ask":
            if args.agent == "none":
                payload = ask_scope_as_json(
                    args.prompt,
                    args.scope,
                    config.vault_path,
                    context_mode=args.context_mode,
                    agent=args.agent,
                )
                print(payload)
                return 0
            bundle = ask_scope(
                args.prompt,
                args.scope,
                config.vault_path,
                context_mode=args.context_mode,
                agent=args.agent,
            )
            if args.json:
                print(json.dumps(asdict(bundle), ensure_ascii=False, indent=2))
            else:
                print(bundle.answer_markdown, end="" if bundle.answer_markdown.endswith("\n") else "\n")
            return 0
    except (ObsidianCliUnavailableError, CodexCliUnavailableError, RuntimeError, FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
