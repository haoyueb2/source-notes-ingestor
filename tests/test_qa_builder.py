import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from obsidian_knowledge_ingestor.qa_builder import (
    VaultNoteRecord,
    _build_corpus_index_body,
    _build_scope_map_prompt,
    _write_derived_note,
    build_scope_package,
)


class QaBuilderTests(unittest.TestCase):
    def test_build_corpus_index_body_is_compact(self) -> None:
        scope = type("Scope", (), {"display_name": "Demo"})()
        body = _build_corpus_index_body(
            scope,
            [
                VaultNoteRecord(
                    path=Path("/vault/Sources/Zhihu/demo/answers/one.md"),
                    relpath="Sources/Zhihu/demo/answers/one.md",
                    source="zhihu",
                    content_type="answer",
                    title="One",
                    author_name="Demo",
                    published_at="2024-01-01",
                    updated_at="2024-01-02",
                    summary="A" * 180,
                    body="Body one.",
                )
            ],
        )
        self.assertIn("Compact retrieval-oriented note index", body)
        self.assertIn("- [001] `One`", body)
        self.assertIn("summary: ", body)
        self.assertNotIn("## 001. One", body)
        self.assertNotIn("A" * 180, body)

    def test_scope_map_prompt_requires_deep_overview_and_theme_atlas(self) -> None:
        prompt = _build_scope_map_prompt(
            "demo",
            "Demo",
            Path("/vault/Derived/Scopes/demo/manifest.md"),
            Path("/vault/Derived/Scopes/demo/corpus_index.md"),
            Path("/vault/Derived/Scopes/demo/full_context.md"),
        )
        self.assertIn("2500-4500 Chinese characters", prompt)
        self.assertIn("## Tensions and Contradictions", prompt)
        self.assertIn("# Theme Atlas: Demo", prompt)
        self.assertIn("12-18 theme sections", prompt)

    def test_build_scope_package_writes_programmatic_and_codex_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            vault = root / "vault"
            zhihu = vault / "Sources" / "Zhihu" / "demo" / "answers"
            wechat = vault / "Sources" / "WeChat" / "demo"
            zhihu.mkdir(parents=True)
            wechat.mkdir(parents=True)
            (zhihu / "one.md").write_text(
                """---
source: "zhihu"
author_name: "Demo"
content_type: "answer"
title: "One"
summary: "First"
---
Body one.
""",
                encoding="utf-8",
            )
            (wechat / "two.md").write_text(
                """---
source: "wechat"
author_name: "Demo"
content_type: "article"
title: "Two"
summary: "Second"
---
Body two.
""",
                encoding="utf-8",
            )
            scopes = root / "scopes"
            scopes.mkdir()
            (scopes / "demo.json").write_text(
                json.dumps(
                    {
                        "scope_id": "demo",
                        "display_name": "Demo",
                        "sources": [
                            {"path": "Sources/Zhihu/demo", "source": "zhihu"},
                            {"path": "Sources/WeChat/demo", "source": "wechat"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def fake_generate(scope_id, display_name, derived_dir, note_paths, vault_path):
                overview = _write_derived_note(derived_dir / "overview.md", scope_id, "overview", "# Overview\n", note_paths)
                themes = _write_derived_note(derived_dir / "themes.md", scope_id, "themes", "# Themes\n", note_paths)
                return {
                    "overview": str(overview.relative_to(vault_path)),
                    "themes": str(themes.relative_to(vault_path)),
                }

            with patch("obsidian_knowledge_ingestor.qa_builder._generate_codex_derived_notes", side_effect=fake_generate):
                manifest = build_scope_package("demo", vault, scopes_dir=scopes, rebuild=True)

        self.assertEqual(manifest.note_count, 2)
        self.assertIn("manifest", manifest.generated_files)
        self.assertIn("overview", manifest.generated_files)
        self.assertIn("themes", manifest.generated_files)
        self.assertEqual(manifest.source_counts, {"wechat": 1, "zhihu": 1})

    def test_rebuild_only_replaces_derived_scope_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            vault = root / "vault"
            source_dir = vault / "Sources" / "Zhihu" / "demo" / "answers"
            source_dir.mkdir(parents=True)
            source_note = source_dir / "one.md"
            source_note.write_text(
                """---
source: "zhihu"
title: "One"
content_type: "answer"
summary: "First"
---
Body one.
""",
                encoding="utf-8",
            )
            derived_dir = vault / "Derived" / "Scopes" / "demo"
            derived_dir.mkdir(parents=True)
            stale_file = derived_dir / "stale.md"
            stale_file.write_text("stale", encoding="utf-8")
            scopes = root / "scopes"
            scopes.mkdir()
            (scopes / "demo.json").write_text(
                json.dumps({"scope_id": "demo", "display_name": "Demo", "sources": [{"path": "Sources/Zhihu/demo"}]}),
                encoding="utf-8",
            )

            def fake_generate(scope_id, display_name, derived_dir, note_paths, vault_path):
                overview = _write_derived_note(derived_dir / "overview.md", scope_id, "overview", "# Overview\n", note_paths)
                themes = _write_derived_note(derived_dir / "themes.md", scope_id, "themes", "# Themes\n", note_paths)
                return {
                    "overview": str(overview.relative_to(vault_path)),
                    "themes": str(themes.relative_to(vault_path)),
                }

            with patch("obsidian_knowledge_ingestor.qa_builder._generate_codex_derived_notes", side_effect=fake_generate):
                build_scope_package("demo", vault, scopes_dir=scopes, rebuild=True)

            self.assertTrue(source_note.exists())
            self.assertFalse(stale_file.exists())


if __name__ == "__main__":
    unittest.main()
