from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .browser_automation import BrowserAutomationError, default_storage_state_path, default_user_data_dir, save_login_session
from .qa_builder import CodexUnavailableError, build_scope_package
from .config import AppConfig, DEFAULT_OBSIDIAN_VAULT_PATH, load_target
from .models import AskResultBundle, AskSession, AskTurn, AskUsage
from .pipeline import IngestReport, ingest_source
from .qa_runner import (
    CodexCliUnavailableError,
    ObsidianCliUnavailableError,
    ask_scope,
    ask_scope_with_session,
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
DEFAULT_SCOPE_ID = "linlin"
DEFAULT_CONTEXT_MODE = "map"


def _vault_help_text() -> str:
    return f"Override Obsidian vault path (default: {DEFAULT_OBSIDIAN_VAULT_PATH})"


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return text
    return parts[2]


class _BufferingTee:
    def __init__(self, stream, buffer):
        self._stream = stream
        self._buffer = buffer

    def write(self, text: str) -> int:
        self._stream.write(text)
        self._buffer.write(text)
        return len(text)

    def flush(self) -> None:
        self._stream.flush()
        self._buffer.flush()


def _default_ask_log_path(config: AppConfig, scope: str) -> Path:
    logs_dir = config.state_dir / "ask_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    return logs_dir / f"{timestamp}-{slugify(scope)}.log"


def _session_dir(config: AppConfig) -> Path:
    path = config.state_dir / "ask_sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _answer_dir(config: AppConfig, session_id: str) -> Path:
    path = config.state_dir / "ask_answers" / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _session_path(config: AppConfig, session_id: str) -> Path:
    return _session_dir(config) / f"{session_id}.json"


def _answer_path_for_turn(config: AppConfig, session_id: str, turn_id: str) -> Path:
    return _answer_dir(config, session_id) / f"{turn_id}.md"


def _write_ask_answer(config: AppConfig, session_id: str, turn_id: str, answer_markdown: str) -> Path:
    answer_path = _answer_path_for_turn(config, session_id, turn_id)
    answer_path.write_text(answer_markdown, encoding="utf-8")
    return answer_path


@contextlib.contextmanager
def _ask_capture_context():
    from io import StringIO

    stdout_buffer = StringIO()
    stderr_buffer = StringIO()
    stderr_tee = _BufferingTee(sys.stderr, stderr_buffer)
    stdout_tee = _BufferingTee(sys.stdout, stdout_buffer)
    with contextlib.redirect_stderr(stderr_tee), contextlib.redirect_stdout(stdout_tee):
        yield {"stdout": stdout_buffer, "stderr": stderr_buffer}


def _write_ask_log(config: AppConfig, scope: str, capture: dict[str, Any]) -> Path:
    log_path = _default_ask_log_path(config, scope)
    payload = capture["stderr"].getvalue() + capture["stdout"].getvalue()
    log_path.write_text(payload, encoding="utf-8")
    return log_path


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_session_id(scope: str) -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{slugify(scope)}"


def _new_turn_id(turn_index: int) -> str:
    return f"turn-{turn_index:04d}"


def _session_from_payload(payload: dict[str, Any]) -> AskSession:
    turns = []
    for raw_turn in payload.get("turns", []):
        raw_usage = raw_turn.get("usage") or {}
        turns.append(
            AskTurn(
                turn_id=raw_turn["turn_id"],
                parent_turn_id=raw_turn.get("parent_turn_id"),
                created_at=raw_turn["created_at"],
                user_prompt=raw_turn["user_prompt"],
                question_reframing=raw_turn.get("question_reframing") or raw_turn["user_prompt"],
                query_plan=list(raw_turn.get("query_plan") or []),
                query_runs=list(raw_turn.get("query_runs") or []),
                evidence_bundle=list(raw_turn.get("evidence_bundle") or []),
                answer_markdown_path=raw_turn.get("answer_markdown_path"),
                answer_markdown=raw_turn.get("answer_markdown"),
                usage=AskUsage(
                    input_tokens=int(raw_usage.get("input_tokens") or 0),
                    cached_input_tokens=int(raw_usage.get("cached_input_tokens") or 0),
                    output_tokens=int(raw_usage.get("output_tokens") or 0),
                ),
                used_retrieval=bool(raw_turn.get("used_retrieval", True)),
                retrieval_reason=raw_turn.get("retrieval_reason"),
            )
        )
    return AskSession(
        session_id=payload["session_id"],
        scope_id=payload["scope_id"],
        context_mode=payload["context_mode"],
        agent=payload["agent"],
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
        turns=turns,
        title=payload.get("title"),
        source_answer_path=payload.get("source_answer_path"),
    )


def _load_session_from_json(path: Path) -> AskSession:
    return _session_from_payload(load_json(path))


def _parse_citations(answer_markdown: str) -> list[str]:
    citations: list[str] = []
    seen: set[str] = set()
    in_citations = False
    for line in answer_markdown.splitlines():
        stripped = line.strip()
        if stripped == "## Citations":
            in_citations = True
            continue
        if in_citations and stripped.startswith("## "):
            break
        if not in_citations or not stripped.startswith("- "):
            continue
        path = stripped[2:].strip().strip("`")
        if path and path not in seen:
            seen.add(path)
            citations.append(path)
    return citations


def _restore_legacy_session(answer_path: Path, scope: str, context_mode: str, agent: str) -> AskSession:
    session_id = f"legacy-{slugify(answer_path.stem)}"
    answer_markdown = answer_path.read_text(encoding="utf-8")
    now = _now_iso()
    evidence_bundle = [{"path": path, "queries": [], "snippets": [], "title": Path(path).stem, "source": "unknown", "content_type": "note"} for path in _parse_citations(answer_markdown)]
    return AskSession(
        session_id=session_id,
        scope_id=scope,
        context_mode=context_mode,
        agent=agent,
        created_at=now,
        updated_at=now,
        turns=[
            AskTurn(
                turn_id="turn-0001",
                parent_turn_id=None,
                created_at=now,
                user_prompt="Legacy answer restore",
                question_reframing="Legacy answer restore",
                evidence_bundle=evidence_bundle,
                answer_markdown_path=str(answer_path),
                answer_markdown=answer_markdown,
                used_retrieval=False,
                retrieval_reason="Restored from legacy answer markdown.",
            )
        ],
        title=answer_path.stem,
        source_answer_path=str(answer_path),
    )


def _resolve_session(config: AppConfig, scope: str, session_ref: str | None, resume: bool, new_session: bool, context_mode: str, agent: str) -> AskSession | None:
    if new_session:
        return None
    if session_ref:
        candidate = Path(session_ref).expanduser()
        if candidate.exists() and candidate.suffix == ".md":
            return _restore_legacy_session(candidate, scope, context_mode, agent)
        json_path = candidate if candidate.exists() else _session_path(config, session_ref)
        if json_path.exists():
            return _load_session_from_json(json_path)
        raise FileNotFoundError(f"Ask session not found: {session_ref}")
    if not resume:
        return None
    candidates = sorted(_session_dir(config).glob(f"*-{slugify(scope)}.json"))
    if not candidates:
        return None
    return _load_session_from_json(candidates[-1])


def _save_session(config: AppConfig, session: AskSession) -> Path:
    path = _session_path(config, session.session_id)
    dump_json(path, asdict(session))
    return path


def _append_turn(session: AskSession, bundle: AskResultBundle, answer_path: Path) -> AskSession:
    now = _now_iso()
    turn_id = bundle.turn_id or _new_turn_id(len(session.turns) + 1)
    turn = AskTurn(
        turn_id=turn_id,
        parent_turn_id=session.turns[-1].turn_id if session.turns else None,
        created_at=now,
        user_prompt=bundle.prompt,
        question_reframing=bundle.question_reframing or bundle.prompt,
        query_plan=bundle.query_plan,
        query_runs=bundle.query_runs,
        evidence_bundle=bundle.evidence_bundle,
        answer_markdown_path=str(answer_path),
        usage=bundle.usage,
        used_retrieval=bundle.used_retrieval,
        retrieval_reason=bundle.retrieval_reason,
    )
    session.turns.append(turn)
    session.updated_at = now
    if not session.title:
        session.title = bundle.prompt[:80]
    return session


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
    ingest_parser.add_argument("--vault", help=_vault_help_text())

    verify_parser = subparsers.add_parser("verify", help="Verify ingestion counts against source-visible counts")
    verify_parser.add_argument("source", choices=["zhihu"])
    verify_parser.add_argument("--target", required=True, help="Path to source target JSON")
    verify_parser.add_argument("--vault", help=_vault_help_text())
    verify_parser.add_argument("--out", help="Optional JSON report output path")

    discover_parser = subparsers.add_parser("discover", help="Discover source URLs without ingesting content")
    discover_parser.add_argument("source", choices=["wechat"])
    discover_parser.add_argument("--target", required=True, help="Path to source target JSON")
    discover_parser.add_argument("--output-dir", help="Directory for screenshots and debug artifacts")

    search_parser = subparsers.add_parser("search", help="Search the Obsidian vault via official CLI")
    search_parser.add_argument("query")
    search_parser.add_argument("--vault", help=_vault_help_text())

    read_parser = subparsers.add_parser("read", help="Read a vault note via official CLI")
    read_parser.add_argument("path")
    read_parser.add_argument("--vault", help=_vault_help_text())
    read_parser.add_argument("--body-only", action="store_true")

    build_qa_parser = subparsers.add_parser("build-qa", help="Build a derived QA package for a scope")
    build_qa_parser.add_argument("--scope", default=DEFAULT_SCOPE_ID, help=f"Scope id (default: {DEFAULT_SCOPE_ID})")
    build_qa_parser.add_argument("--vault", help=_vault_help_text())
    build_qa_parser.add_argument("--rebuild", action="store_true")

    qa_search_parser = subparsers.add_parser("qa-search", help="Search raw scope notes through the official Obsidian CLI")
    qa_search_parser.add_argument("--scope", default=DEFAULT_SCOPE_ID, help=f"Scope id (default: {DEFAULT_SCOPE_ID})")
    qa_search_parser.add_argument("--query", required=True)
    qa_search_parser.add_argument("--vault", help=_vault_help_text())
    qa_search_parser.add_argument("--limit", type=int, default=8)

    qa_read_parser = subparsers.add_parser("qa-read", help="Read a note path through the official Obsidian CLI")
    qa_read_parser.add_argument("--path", required=True)
    qa_read_parser.add_argument("--vault", help=_vault_help_text())
    qa_read_parser.add_argument("--body-only", action="store_true")

    qa_open_parser = subparsers.add_parser("qa-open-derived", help="Read a derived scope note through the official Obsidian CLI")
    qa_open_parser.add_argument("--scope", default=DEFAULT_SCOPE_ID, help=f"Scope id (default: {DEFAULT_SCOPE_ID})")
    qa_open_parser.add_argument("--kind", required=True, choices=["overview", "themes", "corpus_index", "full_context", "manifest"])
    qa_open_parser.add_argument("--vault", help=_vault_help_text())
    qa_open_parser.add_argument("--body-only", action="store_true")

    ask_parser = subparsers.add_parser("ask", help="Run agentic Q&A against a scope")
    ask_parser.add_argument("prompt")
    ask_parser.add_argument("--scope", default=DEFAULT_SCOPE_ID, help=f"Scope id (default: {DEFAULT_SCOPE_ID})")
    ask_parser.add_argument(
        "--context-mode",
        choices=["map", "fulltext"],
        default=DEFAULT_CONTEXT_MODE,
        help=f"Retrieval context mode (default: {DEFAULT_CONTEXT_MODE})",
    )
    ask_parser.add_argument("--agent", choices=["codex", "none"], default="codex")
    ask_parser.add_argument("--json", action="store_true")
    ask_parser.add_argument("--session", help="Session id, session JSON path, or legacy answer Markdown path")
    ask_parser.add_argument("--resume", action="store_true", help="Resume the latest session for the scope")
    ask_parser.add_argument("--new-session", action="store_true", help="Force creation of a new ask session")
    ask_parser.add_argument("--debug-log", action="store_true", help="Persist a full debug log for the ask run")
    ask_parser.add_argument("--vault", help=_vault_help_text())

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
            if args.session and args.resume:
                raise ValueError("`oki ask` cannot use `--session` and `--resume` together.")
            if args.session and args.new_session:
                raise ValueError("`oki ask` cannot use `--session` and `--new-session` together.")
            if args.resume and args.new_session:
                raise ValueError("`oki ask` cannot use `--resume` and `--new-session` together.")
            with _ask_capture_context() as capture:
                session = _resolve_session(
                    config,
                    args.scope,
                    args.session,
                    args.resume,
                    args.new_session,
                    args.context_mode,
                    args.agent,
                )
                session_id = session.session_id if session is not None else _new_session_id(args.scope)
                turn_id = _new_turn_id((len(session.turns) if session is not None else 0) + 1)
                try:
                    if args.agent == "none":
                        bundle = ask_scope(
                            args.prompt,
                            args.scope,
                            config.vault_path,
                            context_mode=args.context_mode,
                            agent=args.agent,
                            stream_final_answer=not args.json,
                        )
                    else:
                        bundle = ask_scope_with_session(
                            args.prompt,
                            args.scope,
                            config.vault_path,
                            session=session,
                            context_mode=args.context_mode,
                            agent=args.agent,
                            stream_final_answer=not args.json,
                        )
                except Exception:
                    log_path = _write_ask_log(config, args.scope, capture)
                    print(f"[oki ask] debug log: {log_path}", file=sys.stderr)
                    raise
                bundle.session_id = session_id
                bundle.turn_id = turn_id
                answer_path = _write_ask_answer(config, session_id, turn_id, bundle.answer_markdown)
                bundle.answer_markdown_path = str(answer_path)
                active_session = session or AskSession(
                    session_id=session_id,
                    scope_id=args.scope,
                    context_mode=args.context_mode,
                    agent=args.agent,
                    created_at=_now_iso(),
                    updated_at=_now_iso(),
                    turns=[],
                )
                _append_turn(active_session, bundle, answer_path)
                session_path = _save_session(config, active_session)
                if args.debug_log:
                    log_path = _write_ask_log(config, args.scope, capture)
                    print(f"[oki ask] debug log: {log_path}", file=sys.stderr)
                if args.json:
                    print(json.dumps(asdict(bundle), ensure_ascii=False, indent=2))
                elif not bundle.answer_streamed:
                    print(bundle.answer_markdown, end="" if bundle.answer_markdown.endswith("\n") else "\n")
                print(f"[oki ask] answer file: {answer_path}", file=sys.stderr)
                print(f"[oki ask] session file: {session_path}", file=sys.stderr)
            return 0
    except (ObsidianCliUnavailableError, CodexCliUnavailableError, RuntimeError, FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
