from types import SimpleNamespace
import unittest
from unittest.mock import patch

from obsidian_knowledge_ingestor.adapters.zhihu import fetch_source


class ZhihuBrowserAdapterTests(unittest.TestCase):
    def test_browser_mode_discovers_and_fetches_profile_pages(self) -> None:
        target = {
            "author_name": "Demo User",
            "profile_url": "https://www.zhihu.com/people/demo-user",
            "browser": {
                "enabled": True,
                "storage_state": "/tmp/zhihu.json",
                "headless": True,
                "max_items": 5,
            },
        }
        pages = [
            SimpleNamespace(
                url="https://www.zhihu.com/question/1/answer/2",
                html="<html><head><title>Answer</title></head><body><article><p>Body</p></article></body></html>",
            )
        ]
        with patch("obsidian_knowledge_ingestor.adapters.zhihu.discover_zhihu_profile_urls", return_value=[pages[0].url]), patch(
            "obsidian_knowledge_ingestor.adapters.zhihu.fetch_pages_with_browser", return_value=pages
        ):
            items = fetch_source(target, auth_ctx=None, since=None)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].content_type, "answer")
        self.assertEqual(items[0].title, "Answer")


if __name__ == "__main__":
    unittest.main()
