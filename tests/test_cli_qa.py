import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from obsidian_knowledge_ingestor.cli import build_parser, main
from obsidian_knowledge_ingestor.config import AppConfig, DEFAULT_OBSIDIAN_VAULT_PATH
from obsidian_knowledge_ingestor.models import AskResultBundle, AskSession, AskTurn, AskUsage, DerivedScopeManifest


class CliQaTests(unittest.TestCase):
    def test_app_config_uses_repo_default_vault_path(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = AppConfig.from_env()
        self.assertEqual(config.vault_path, Path(DEFAULT_OBSIDIAN_VAULT_PATH).expanduser())

    def test_ask_parser_defaults_scope_context_and_vault_help(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["ask", "问题"])
        self.assertEqual(args.scope, "linlin")
        self.assertEqual(args.context_mode, "map")
        self.assertIsNone(args.vault)
        self.assertFalse(args.resume)
        self.assertFalse(args.new_session)
        self.assertFalse(args.debug_log)
        with self.assertRaises(SystemExit):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                parser.parse_args(["ask", "--help"])
        help_text = stdout.getvalue()
        self.assertIn("linlin", help_text)
        self.assertIn(DEFAULT_OBSIDIAN_VAULT_PATH, help_text)

    def test_build_qa_command_prints_manifest_json(self) -> None:
        manifest = DerivedScopeManifest(
            scope_id="demo",
            display_name="Demo",
            derived_dir="Derived/Scopes/demo",
            source_roots=["Sources/Zhihu/demo"],
            source_note_paths=["Sources/Zhihu/demo/answers/one.md"],
            generated_files={"manifest": "Derived/Scopes/demo/manifest.md"},
            note_count=1,
            source_counts={"zhihu": 1},
        )
        stdout = io.StringIO()
        with patch("obsidian_knowledge_ingestor.cli.build_scope_package", return_value=manifest):
            with redirect_stdout(stdout):
                code = main(["build-qa", "--scope", "demo"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["scope_id"], "demo")

    def test_ask_command_json_mode_prints_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            vault = root / "vault"
            state = root / "state"
            vault.mkdir()
            stdout = io.StringIO()
            bundle = AskResultBundle(
                prompt="问题",
                scope_id="demo",
                context_mode="map",
                agent="codex",
                answer_markdown="## Analysis Trace\n\ntrace",
                usage=AskUsage(input_tokens=1, cached_input_tokens=2, output_tokens=3),
            )
            config = AppConfig(vault_path=vault, state_dir=state, raw_data_dir=root / "raw")
            with patch("obsidian_knowledge_ingestor.cli.AppConfig.from_env", return_value=config):
                with patch("obsidian_knowledge_ingestor.cli.ask_scope_with_session", return_value=bundle):
                    with redirect_stdout(stdout):
                        code = main(["ask", "问题", "--scope", "demo", "--vault", str(vault), "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["scope_id"], "demo")
            self.assertIn("session_id", payload)
            sessions = list((state / "ask_sessions").glob("*.json"))
            self.assertEqual(len(sessions), 1)

    def test_ask_command_writes_answer_and_session_without_default_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            vault = root / "vault"
            state = root / "state"
            vault.mkdir()
            stderr = io.StringIO()
            stdout = io.StringIO()
            bundle = AskResultBundle(
                prompt="问题",
                scope_id="demo",
                context_mode="map",
                agent="codex",
                answer_markdown="## Answer\n",
                answer_streamed=True,
                usage=AskUsage(output_tokens=4),
            )
            config = AppConfig(vault_path=vault, state_dir=state, raw_data_dir=root / "raw")
            with patch("obsidian_knowledge_ingestor.cli.AppConfig.from_env", return_value=config):
                with patch("obsidian_knowledge_ingestor.cli.ask_scope_with_session", return_value=bundle):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = main(["ask", "问题", "--scope", "demo", "--vault", str(vault)])
            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue(), "")
            logs = list((state / "ask_logs").glob("*.log"))
            self.assertEqual(len(logs), 0)
            answers = list((state / "ask_answers").glob("*/*.md"))
            self.assertEqual(len(answers), 1)
            self.assertEqual(answers[0].read_text(encoding="utf-8"), bundle.answer_markdown)
            sessions = list((state / "ask_sessions").glob("*.json"))
            self.assertEqual(len(sessions), 1)
            self.assertIn("[oki ask] answer file:", stderr.getvalue())

    def test_ask_command_falls_back_to_final_print_and_can_write_debug_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            vault = root / "vault"
            state = root / "state"
            vault.mkdir()
            stderr = io.StringIO()
            stdout = io.StringIO()
            bundle = AskResultBundle(
                prompt="问题",
                scope_id="demo",
                context_mode="map",
                agent="codex",
                answer_markdown="## Answer\n\nbody\n",
                answer_streamed=False,
                usage=AskUsage(output_tokens=5),
            )
            config = AppConfig(vault_path=vault, state_dir=state, raw_data_dir=root / "raw")
            with patch("obsidian_knowledge_ingestor.cli.AppConfig.from_env", return_value=config):
                with patch("obsidian_knowledge_ingestor.cli.ask_scope_with_session", return_value=bundle):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = main(["ask", "问题", "--scope", "demo", "--vault", str(vault), "--debug-log"])
            self.assertEqual(code, 0)
            self.assertIn("## Answer", stdout.getvalue())
            logs = list((state / "ask_logs").glob("*.log"))
            self.assertEqual(len(logs), 1)
            answers = list((state / "ask_answers").glob("*/*.md"))
            self.assertEqual(len(answers), 1)
            self.assertEqual(answers[0].read_text(encoding="utf-8"), bundle.answer_markdown)
            self.assertIn("[oki ask] debug log:", stderr.getvalue())

    def test_ask_resume_uses_latest_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            vault = root / "vault"
            state = root / "state"
            vault.mkdir()
            config = AppConfig(vault_path=vault, state_dir=state, raw_data_dir=root / "raw")
            session = AskSession(
                session_id="20260315-foo-demo",
                scope_id="demo",
                context_mode="map",
                agent="codex",
                created_at="2026-03-15T00:00:00Z",
                updated_at="2026-03-15T00:00:00Z",
                turns=[
                    AskTurn(
                        turn_id="turn-0001",
                        parent_turn_id=None,
                        created_at="2026-03-15T00:00:00Z",
                        user_prompt="老问题",
                        question_reframing="老问题",
                    )
                ],
            )
            session_dir = state / "ask_sessions"
            session_dir.mkdir(parents=True)
            (session_dir / "20260315-foo-demo.json").write_text(json.dumps({
                "session_id": session.session_id,
                "scope_id": session.scope_id,
                "context_mode": session.context_mode,
                "agent": session.agent,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "turns": [json.loads(json.dumps({
                    "turn_id": "turn-0001",
                    "parent_turn_id": None,
                    "created_at": "2026-03-15T00:00:00Z",
                    "user_prompt": "老问题",
                    "question_reframing": "老问题",
                    "query_plan": [],
                    "query_runs": [],
                    "evidence_bundle": [],
                    "usage": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0},
                    "used_retrieval": True,
                }))],
            }, ensure_ascii=False), encoding="utf-8")
            bundle = AskResultBundle(
                prompt="新问题",
                scope_id="demo",
                context_mode="map",
                agent="codex",
                answer_markdown="## Answer\n\nbody\n",
            )
            with patch("obsidian_knowledge_ingestor.cli.AppConfig.from_env", return_value=config):
                with patch("obsidian_knowledge_ingestor.cli.ask_scope_with_session", return_value=bundle) as ask_mock:
                    code = main(["ask", "新问题", "--scope", "demo", "--vault", str(vault), "--resume"])
            self.assertEqual(code, 0)
            passed_session = ask_mock.call_args.kwargs["session"]
            self.assertEqual(passed_session.session_id, session.session_id)


if __name__ == "__main__":
    unittest.main()
