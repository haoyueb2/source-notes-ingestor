from datetime import UTC, datetime
from pathlib import Path
import unittest

from obsidian_knowledge_ingestor.config import AppConfig
from obsidian_knowledge_ingestor.models import CanonicalNote
from obsidian_knowledge_ingestor.vault_writer import write_note


class VaultWriterTests(unittest.TestCase):
    def test_write_note_materializes_frontmatter_and_state(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            vault_path = root / "vault"
            config = AppConfig(vault_path=vault_path, state_dir=root / "state", raw_data_dir=root / "raw")
            note = CanonicalNote(
                source="wechat",
                author_id="acct",
                author_name="Example Account",
                content_id="item-1",
                content_type="article",
                title="My Article",
                url="https://example.com/article",
                published_at=datetime(2026, 3, 7, tzinfo=UTC),
                updated_at=datetime(2026, 3, 7, tzinfo=UTC),
                tags=["tag1"],
                summary="summary",
                markdown_body="# Title\n\nBody\n",
                raw_html_path=None,
                assets=[],
                checksum="abc123",
            )

            note_path = write_note(note, vault_path, config=config, raw_html="<article>Body</article>")

            self.assertTrue(note_path.exists())
            content = note_path.read_text(encoding="utf-8")
            self.assertIn('source: "wechat"', content)
            self.assertIn("# Title", content)
            state_path = vault_path / "Sources/_state/wechat-example-account.json"
            self.assertTrue(state_path.exists())
            self.assertEqual(note_path.name, "My-Article.md")

    def test_wechat_title_collision_falls_back_to_content_id(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            vault_path = root / "vault"
            config = AppConfig(vault_path=vault_path, state_dir=root / "state", raw_data_dir=root / "raw")
            base_kwargs = dict(
                source="wechat",
                author_id="acct",
                author_name="Example Account",
                content_type="article",
                title="Repeated Title",
                url="https://example.com/article",
                published_at=datetime(2026, 3, 7, tzinfo=UTC),
                updated_at=datetime(2026, 3, 7, tzinfo=UTC),
                tags=[],
                summary="summary",
                markdown_body="# Title\n\nBody\n",
                raw_html_path=None,
            )

            first = CanonicalNote(content_id="item-1", assets=[], checksum="abc123", **base_kwargs)
            second = CanonicalNote(content_id="item-2", assets=[], checksum="def456", **base_kwargs)

            first_path = write_note(first, vault_path, config=config, raw_html="<article>Body</article>")
            second_path = write_note(second, vault_path, config=config, raw_html="<article>Body</article>")

            self.assertEqual(first_path.name, "Repeated-Title.md")
            self.assertEqual(second_path.name, "Repeated-Title-item-2.md")


if __name__ == "__main__":
    unittest.main()
