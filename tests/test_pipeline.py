import json
from datetime import UTC, datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from obsidian_knowledge_ingestor.config import AppConfig
from obsidian_knowledge_ingestor.models import RawItem
from obsidian_knowledge_ingestor.pipeline import ingest_source


class PipelineTests(unittest.TestCase):
    def test_ingest_source_skips_unchanged_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            vault_path = root / "vault"
            target_path = root / "target.json"
            target_path.write_text(json.dumps({"feed_url": "https://example.com/feed.xml", "author_name": "Demo"}), encoding="utf-8")
            config = AppConfig(vault_path=vault_path, state_dir=root / "state", raw_data_dir=root / "raw")

            raw_item = RawItem(
                source="zhihu",
                author_id="demo",
                author_name="Demo",
                content_id="123",
                content_type="answer",
                title="Title",
                url="https://example.com/a",
                published_at=datetime(2026, 3, 7, tzinfo=UTC),
                updated_at=datetime(2026, 3, 7, tzinfo=UTC),
                summary="summary",
                raw_html="<article><p>Body</p></article>",
            )

            with patch(
                "obsidian_knowledge_ingestor.pipeline.FETCHERS",
                {"zhihu": lambda target, auth_ctx, since: [raw_item], "wechat": lambda target, auth_ctx, since: []},
            ):
                first = ingest_source("zhihu", target_path, config=config)
                second = ingest_source("zhihu", target_path, config=config)

            self.assertEqual(first.written, 1)
            self.assertEqual(second.skipped, 1)


if __name__ == "__main__":
    unittest.main()
