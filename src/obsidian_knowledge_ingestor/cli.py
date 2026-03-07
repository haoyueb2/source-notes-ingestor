from __future__ import annotations

import argparse
import json
import sys

from .config import AppConfig
from .pipeline import ingest_source
from .qa_runner import ObsidianCliUnavailableError, query_vault, read_note, search


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oki", description="Obsidian knowledge ingestion CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Ingest content from a supported source")
    ingest_parser.add_argument("source", choices=["zhihu", "wechat"])
    ingest_parser.add_argument("--target", required=True, help="Path to source target JSON")
    ingest_parser.add_argument("--vault", help="Override Obsidian vault path")

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
        config.vault_path = config.vault_path.__class__(args.vault).expanduser()

    if args.command == "ingest":
        try:
            report = ingest_source(args.source, args.target, config=config)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(report.__dict__, ensure_ascii=False, indent=2))
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
