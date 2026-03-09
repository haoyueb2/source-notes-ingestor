import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from obsidian_knowledge_ingestor.models import QueryResult
from obsidian_knowledge_ingestor.qa_runner import (
    ObsidianCliUnavailableError,
    _build_agent_prompt,
    _extract_paths_from_search_stdout,
    _obsidian_binary,
    ask_scope,
    search,
    search_scope,
)


class QaRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        _obsidian_binary.cache_clear()

    def tearDown(self) -> None:
        _obsidian_binary.cache_clear()

    def test_rejects_non_official_obsidian_cli(self) -> None:
        with patch("obsidian_knowledge_ingestor.qa_runner.shutil.which", return_value="/tmp/node_modules/obsidian-cli/cli.js"):
            with self.assertRaises(ObsidianCliUnavailableError):
                _obsidian_binary()

    def test_search_builds_official_cli_command(self) -> None:
        with patch("obsidian_knowledge_ingestor.qa_runner._obsidian_binary", return_value="obsidian"):
            with patch(
                "obsidian_knowledge_ingestor.qa_runner._run",
                side_effect=lambda command, cwd=None: QueryResult(command=command, stdout="", stderr="", returncode=0),
            ):
                result = search("deep thought", cwd="/vault", path="Sources/Zhihu/demo", format="json", limit=5)

        self.assertEqual(
            result.command,
            ["obsidian", "search", "query=deep thought", "path=Sources/Zhihu/demo", "format=json", "limit=5"],
        )

    def test_search_scope_returns_structured_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            vault = root / "vault"
            scopes = root / "scopes"
            scopes.mkdir()
            (scopes / "demo.json").write_text(
                json.dumps(
                    {
                        "scope_id": "demo",
                        "display_name": "Demo",
                        "sources": [
                            {
                                "path": "Sources/Zhihu/demo",
                                "source": "zhihu",
                                "author_name": "Demo",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def fake_search(query: str, vault=None, cwd=None, path=None, format=None, limit=None):
                self.assertEqual(path, "Sources/Zhihu/demo")
                payload = [{"path": "Sources/Zhihu/demo/answers/example.md"}]
                return QueryResult(command=["obsidian"], stdout=json.dumps(payload), stderr="", returncode=0)

            note_text = """---
source: "zhihu"
content_type: "answer"
title: "A Note"
summary: "summary"
---
This line discusses deep thought and reflective practice.
"""

            with patch("obsidian_knowledge_ingestor.qa_runner.search", side_effect=fake_search):
                with patch(
                    "obsidian_knowledge_ingestor.qa_runner.read_note",
                    return_value=QueryResult(command=["obsidian"], stdout=note_text, stderr="", returncode=0),
                ):
                    results = search_scope("demo", "deep thought", vault, scopes_dir=scopes, limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].path, "Sources/Zhihu/demo/answers/example.md")
        self.assertEqual(results[0].title, "A Note")
        self.assertEqual(results[0].source, "zhihu")
        self.assertIn("deep thought", results[0].snippet.lower())

    def test_extract_paths_ignores_no_matches_sentinel(self) -> None:
        self.assertEqual(_extract_paths_from_search_stdout("No matches found.\n"), [])

    def test_ask_scope_builds_agent_prompt_and_reads_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            vault = root / "vault"
            derived = vault / "Derived" / "Scopes" / "demo"
            derived.mkdir(parents=True)
            for name in ["overview.md", "themes.md", "corpus_index.md", "full_context.md"]:
                (derived / name).write_text(f"---\nderived: \"true\"\n---\n# {name}\nbody for {name}\n", encoding="utf-8")
            scopes = root / "scopes"
            scopes.mkdir()
            (scopes / "demo.json").write_text(
                json.dumps(
                    {
                        "scope_id": "demo",
                        "display_name": "Demo",
                        "sources": [{"path": "Sources/Zhihu/demo", "source": "zhihu"}],
                    }
                ),
                encoding="utf-8",
            )

            captured: dict[str, object] = {}

            def fake_run(command, cwd=None, env=None, input=None, capture_output=None, text=None):
                output_path = Path(command[command.index("--output-last-message") + 1])
                output_path.write_text("## Analysis Trace\n\ntrace\n\n## Answer\n\nanswer\n\n## Citations\n\n- Sources/Zhihu/demo/answers/example.md\n", encoding="utf-8")
                captured["command"] = command
                captured["input"] = input
                return QueryResult(command=command, stdout="", stderr="", returncode=0)

            with patch("obsidian_knowledge_ingestor.qa_runner.shutil.which", return_value="/usr/local/bin/codex"):
                with patch("obsidian_knowledge_ingestor.qa_runner.subprocess.run", side_effect=fake_run):
                    bundle = ask_scope("他怎么看成长?", "demo", vault, context_mode="map", scopes_dir=scopes)

        self.assertEqual(bundle.scope_id, "demo")
        self.assertIn("## Analysis Trace", bundle.answer_markdown)
        prompt_text = str(captured["input"])
        self.assertIn("Preloaded derived context:", prompt_text)
        self.assertIn("### BEGIN OVERVIEW", prompt_text)
        self.assertIn("body for overview.md", prompt_text)
        self.assertIn("qa-search --scope demo --query", prompt_text)
        self.assertIn("Every important conclusion must point back to raw note paths.", prompt_text)
        self.assertIn("Perform at least 4 distinct qa-search calls.", prompt_text)
        self.assertIn("Aim for roughly 1200-2500 Chinese characters", prompt_text)

    def test_build_agent_prompt_fulltext_mode_mentions_full_context(self) -> None:
        prompt = _build_agent_prompt("问题", "demo", "fulltext", Path("/vault"))
        self.assertIn("The prompt below already includes overview, themes, and a preloaded full-context extract.", prompt)


if __name__ == "__main__":
    unittest.main()
