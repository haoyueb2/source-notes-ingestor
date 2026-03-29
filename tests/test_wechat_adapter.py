from pathlib import Path
import tempfile
import unittest

from source_notes_ingestor.adapters.wechat import WeChatAccessError, fetch_source


class WeChatAdapterTests(unittest.TestCase):
    def test_seed_page_detects_verification_wall(self) -> None:
        html = "<html><body><h2>环境异常</h2><p>当前环境异常，完成验证后即可继续访问。</p></body></html>"
        with tempfile.TemporaryDirectory() as tmp_dir:
            html_path = Path(tmp_dir) / "wechat.html"
            html_path.write_text(html, encoding="utf-8")
            with self.assertRaises(WeChatAccessError):
                list(
                    fetch_source(
                        {
                            "account_name": "Demo Account",
                            "html_paths": [str(html_path)],
                            "base_url": "https://mp.weixin.qq.com/s/demo",
                        },
                        auth_ctx=None,
                        since=None,
                    )
                )


if __name__ == "__main__":
    unittest.main()
