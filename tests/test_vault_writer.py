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


if __name__ == "__main__":
    unittest.main()
