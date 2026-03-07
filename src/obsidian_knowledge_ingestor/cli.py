from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .browser_automation import BrowserAutomationError, default_storage_state_path, default_user_data_dir, save_login_session
from .config import AppConfig
from .pipeline import ingest_source
from .verification import verify_zhihu_ingestion
from .qa_runner import ObsidianCliUnavailableError, query_vault, read_note, search


DEFAULT_LOGIN_URLS = {
    "zhihu": "https://www.zhihu.com/signin",
    "wechat": "https://mp.weixin.qq.com/",
}


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

    search_parser = subparsers.add_parser("search", help="Search the Obsidian vault via official CLI")
    search_parser.add_argument("query")
    search_parser.add_argument("--vault")

    read_parser = subparsers.add_parser("read", help="Read a vault note via official CLI")
    read_parser.add_argument("path")
    read_parser.add_argument("--vault")

    ask_parser = subparsers.add_parser("ask", help="Run search plus read against the vault")
    ask_parser.add_argument("prompt")
    ask_parser.add_argument("--scope")
    ask_parser.add_argument("--vault")

    return parser


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
        from .config import load_target
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
            report = ingest_source(args.source, args.target, config=config)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
        return 0

    try:
        if args.command == "search":
            result = search(args.query, vault=args.vault, cwd=config.vault_path)
            print(result.stdout, end="")
            return result.returncode
        if args.command == "read":
            result = read_note(args.path, vault=args.vault, cwd=config.vault_path)
            print(result.stdout, end="")
            return result.returncode
        if args.command == "ask":
            for result in query_vault(args.prompt, scope=args.scope, vault=args.vault, cwd=config.vault_path):
                if result.stdout:
                    print(result.stdout, end="")
                if result.stderr:
                    print(result.stderr, file=sys.stderr, end="")
                if result.returncode != 0:
                    return result.returncode
            return 0
    except ObsidianCliUnavailableError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
