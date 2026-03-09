import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from obsidian_knowledge_ingestor.models import EvidenceItem, QueryResult
from obsidian_knowledge_ingestor.qa_runner import (
    ObsidianCliUnavailableError,
    _build_agent_prompt,
    _extract_paths_from_search_stdout,
    _fallback_queries,
    _normalize_query_plan,
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

    def test_normalize_query_plan_adds_fallback_queries(self) -> None:
        reframing, queries = _normalize_query_plan({"question_reframing": "重写问题", "query_plan": []}, "感到无聊老想出去玩social是对的吗")
        self.assertEqual(reframing, "重写问题")
        self.assertGreaterEqual(len(queries), 1)
        self.assertEqual(queries[0]["query"], "感到无聊老想出去玩social是对的吗")

    def test_normalize_query_plan_expands_multi_term_queries(self) -> None:
        _, queries = _normalize_query_plan(
            {
                "question_reframing": "问题重写",
                "query_plan": [
                    {"query": "失败 机会 内耗", "bucket": "surface", "why": "组合查询"},
                ],
            },
            "我因为失败而内耗，担心错过机会",
        )
        values = [item["query"] for item in queries]
        self.assertIn("失败 机会 内耗", values)
        self.assertIn("失败", values)
        self.assertIn("机会", values)
        self.assertIn("内耗", values)

    def test_fallback_queries_extracts_prompt_keywords(self) -> None:
        values = _fallback_queries(
            "一路走来，我有很多失败，回国后还是觉得去硅谷才有最多的机会，如何排解这种内耗呢"
        )
        self.assertIn("失败", values)
        self.assertIn("回国", values)
        self.assertIn("硅谷", values)
        self.assertIn("机会", values)
        self.assertIn("内耗", values)

    def test_ask_scope_plans_retrieval_then_synthesizes_from_evidence(self) -> None:
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

            def fake_plan(prompt, schema, extra_dirs, scopes_dir=None, stream_output=None):
                captured["planning_prompt"] = prompt
                return {
                    "question_reframing": "这不是在问对不对，而是在问这种冲动背后的驱动力是否健康。",
                    "query_plan": [
                        {"query": "无聊", "bucket": "surface", "why": "直接命中表层情绪"},
                        {"query": "独处", "bucket": "motive", "why": "检验是否在逃避独处"},
                        {"query": "朋友", "bucket": "social", "why": "查看她如何谈关系"},
                        {"query": "自由", "bucket": "criteria", "why": "查看评价尺度"},
                    ],
                }

            def fake_search_scope(scope_id, query, vault_path, scopes_dir=None, limit=8):
                if query == "无聊":
                    return [
                        EvidenceItem(
                            path="Sources/Zhihu/demo/answers/example.md",
                            title="A Note",
                            source="zhihu",
                            content_type="answer",
                            snippet="这段内容谈到无聊与反思。",
                            score=8.0,
                        )
                    ]
                if query == "独处":
                    return [
                        EvidenceItem(
                            path="Sources/Zhihu/demo/answers/example-2.md",
                            title="Second Note",
                            source="zhihu",
                            content_type="answer",
                            snippet="这段内容谈到独处。",
                            score=7.0,
                        )
                    ]
                if query == "朋友":
                    return [
                        EvidenceItem(
                            path="Sources/Zhihu/demo/answers/example-3.md",
                            title="Third Note",
                            source="zhihu",
                            content_type="answer",
                            snippet="这段内容谈到朋友。",
                            score=6.0,
                        )
                    ]
                return [
                    EvidenceItem(
                        path="Sources/Zhihu/demo/answers/example-4.md",
                        title="Fourth Note",
                        source="zhihu",
                        content_type="answer",
                        snippet="这段内容谈到自由。",
                        score=5.0,
                    )
                ]

            def fake_read(path, vault=None, cwd=None):
                return QueryResult(
                    command=["obsidian"],
                    stdout=f"---\ntitle: \"{Path(path).stem}\"\n---\n这是 {path} 的正文，包含足够多的上下文。",
                    stderr="",
                    returncode=0,
                )

            def fake_markdown(prompt, extra_dirs, scopes_dir=None, stream_output=None):
                captured["synthesis_prompt"] = prompt
                return "## Analysis Trace\n\ntrace\n\n## Answer\n\nanswer\n\n## Citations\n\n- Sources/Zhihu/demo/answers/example.md\n"

            with patch("obsidian_knowledge_ingestor.qa_runner._run_codex_json", side_effect=fake_plan):
                with patch("obsidian_knowledge_ingestor.qa_runner.search_scope", side_effect=fake_search_scope):
                    with patch("obsidian_knowledge_ingestor.qa_runner.read_note", side_effect=fake_read):
                        with patch("obsidian_knowledge_ingestor.qa_runner._run_codex_markdown", side_effect=fake_markdown):
                            bundle = ask_scope("他怎么看成长?", "demo", vault, context_mode="map", scopes_dir=scopes)

        self.assertEqual(bundle.scope_id, "demo")
        self.assertIn("## Analysis Trace", bundle.answer_markdown)
        planning_prompt = str(captured["planning_prompt"])
        synthesis_prompt = str(captured["synthesis_prompt"])
        self.assertIn("Your job is to produce a high-quality retrieval plan", planning_prompt)
        self.assertIn("### BEGIN OVERVIEW", planning_prompt)
        self.assertIn("body for overview.md", planning_prompt)
        self.assertIn("Raw evidence bundle:", synthesis_prompt)
        self.assertIn("Sources/Zhihu/demo/answers/example.md", synthesis_prompt)
        self.assertIn("Question reframing:", synthesis_prompt)

    def test_build_agent_prompt_fulltext_mode_mentions_full_context(self) -> None:
        prompt = _build_agent_prompt("问题", "demo", "fulltext", Path("/vault"))
        self.assertIn("The prompt below already includes overview, themes, and a preloaded full-context extract.", prompt)


if __name__ == "__main__":
    unittest.main()
