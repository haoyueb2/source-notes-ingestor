from datetime import UTC, datetime
import unittest

from obsidian_knowledge_ingestor.models import RawItem
from obsidian_knowledge_ingestor.normalizer import normalize


class NormalizeTests(unittest.TestCase):
    def test_normalize_zhihu_answer_extracts_markdown_and_assets(self) -> None:
        raw = RawItem(
            source="zhihu",
            author_id="demo-user",
            author_name="Demo User",
            content_id="123",
            content_type="answer",
            title="",
            url="https://www.zhihu.com/question/1/answer/123",
            published_at=datetime(2026, 3, 7, tzinfo=UTC),
            updated_at=datetime(2026, 3, 7, tzinfo=UTC),
            summary="",
            raw_html='''<html><head><title>Answer Title</title></head><body><div class="RichContent-inner"><p>Hello <a href="/people/demo">world</a>.</p><img src="https://example.com/a.png"></div></body></html>''',
            tags=["sample"],
        )

        note = normalize(raw)

        self.assertEqual(note.title, "Answer Title")
        self.assertIn("Hello[world](https://www.zhihu.com/people/demo).", note.markdown_body)
        self.assertEqual(note.assets, ["https://example.com/a.png"])
        self.assertTrue(note.checksum)


if __name__ == "__main__":
    unittest.main()
