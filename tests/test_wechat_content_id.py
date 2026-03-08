import unittest

from obsidian_knowledge_ingestor.adapters.wechat import content_id_from_url


class WeChatContentIdTests(unittest.TestCase):
    def test_query_article_uses_mid_idx_sn(self) -> None:
        url = "https://mp.weixin.qq.com/s?__biz=MzAwMDYwMTQ4Mg%3D%3D&idx=2&mid=2649470534&sn=9709dd887e85d5203e920d8ff9a3f067"
        self.assertEqual(
            content_id_from_url(url),
            "mid-2649470534-idx-2-sn-9709dd887e85d5203e920d8ff9a3f067",
        )

    def test_short_article_keeps_path_slug(self) -> None:
        self.assertEqual(
            content_id_from_url("https://mp.weixin.qq.com/s/PgR1HF-b9r7V37iwNNCgrw"),
            "PgR1HF-b9r7V37iwNNCgrw",
        )


if __name__ == "__main__":
    unittest.main()
