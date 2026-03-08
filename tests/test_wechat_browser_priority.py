import unittest
from unittest.mock import patch

from obsidian_knowledge_ingestor.adapters.wechat import fetch_source


class WeChatBrowserPriorityTests(unittest.TestCase):
    def test_browser_mode_uses_browser_for_page_urls(self) -> None:
        target = {
            "account_name": "Demo",
            "page_urls": ["https://mp.weixin.qq.com/s/demo"],
            "browser": {
                "enabled": True,
                "storage_state": "/tmp/wechat.json",
                "user_data_dir": "/tmp/wechat-profile",
                "headless": False,
            },
        }
        with patch("obsidian_knowledge_ingestor.adapters.wechat._browser_seed_pages", return_value=[("https://mp.weixin.qq.com/s/demo", "<html><title>T</title><body>Body</body></html>")]), patch(
            "obsidian_knowledge_ingestor.adapters.wechat._html_seed_pages", side_effect=AssertionError("html seeds should not be used")
        ):
            items = list(fetch_source(target, auth_ctx=None, since=None))

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "T")


if __name__ == "__main__":
    unittest.main()
