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
from obsidian_knowledge_ingestor.models import AskResultBundle, DerivedScopeManifest


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
            )
            config = AppConfig(vault_path=vault, state_dir=state, raw_data_dir=root / "raw")
            with patch("obsidian_knowledge_ingestor.cli.AppConfig.from_env", return_value=config):
                with patch("obsidian_knowledge_ingestor.cli.ask_scope", return_value=bundle):
                    with redirect_stdout(stdout):
                        code = main(["ask", "问题", "--scope", "demo", "--vault", str(vault), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["scope_id"], "demo")

    def test_ask_command_writes_default_log_file(self) -> None:
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
            )
            config = AppConfig(vault_path=vault, state_dir=state, raw_data_dir=root / "raw")
            with patch("obsidian_knowledge_ingestor.cli.AppConfig.from_env", return_value=config):
                with patch("obsidian_knowledge_ingestor.cli.ask_scope", return_value=bundle):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = main(["ask", "问题", "--scope", "demo", "--vault", str(vault)])
            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue(), "")
            logs = list((state / "ask_logs").glob("*.log"))
            self.assertEqual(len(logs), 1)
            answers = list((state / "ask_logs").glob("*.md"))
            self.assertEqual(len(answers), 1)
            self.assertEqual(answers[0].read_text(encoding="utf-8"), bundle.answer_markdown)
            log_text = logs[0].read_text(encoding="utf-8")
            self.assertIn("[oki ask] log file:", log_text)
            self.assertIn(str(logs[0]), log_text)
            self.assertIn("[oki ask] answer file:", log_text)
            self.assertIn(str(answers[0]), log_text)

    def test_ask_command_falls_back_to_final_print_and_logs_answer(self) -> None:
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
            )
            config = AppConfig(vault_path=vault, state_dir=state, raw_data_dir=root / "raw")
            with patch("obsidian_knowledge_ingestor.cli.AppConfig.from_env", return_value=config):
                with patch("obsidian_knowledge_ingestor.cli.ask_scope", return_value=bundle):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = main(["ask", "问题", "--scope", "demo", "--vault", str(vault)])
            self.assertEqual(code, 0)
            self.assertIn("## Answer", stdout.getvalue())
            logs = list((state / "ask_logs").glob("*.log"))
            self.assertEqual(len(logs), 1)
            answers = list((state / "ask_logs").glob("*.md"))
            self.assertEqual(len(answers), 1)
            self.assertEqual(answers[0].read_text(encoding="utf-8"), bundle.answer_markdown)
            log_text = logs[0].read_text(encoding="utf-8")
            self.assertIn("## Answer", log_text)
            self.assertIn("[oki ask] answer file:", log_text)


if __name__ == "__main__":
    unittest.main()
