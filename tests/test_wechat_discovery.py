from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from obsidian_knowledge_ingestor.wechat_discovery import (
    _extract_urls_from_general_msg_list,
    discover_from_local_profile,
    discover_from_profile_ext,
    normalize_article_url,
)


class WeChatDiscoveryTests(unittest.TestCase):
    def test_normalize_article_url_strips_tracking_params(self) -> None:
        url = (
            "https://mp.weixin.qq.com/s?__biz=MzAwMDYwMTQ4Mg==&mid=2649470534&idx=2&sn=abc"
            "&pass_ticket=secret&exportkey=x&wx_header=0"
        )
        self.assertEqual(
            normalize_article_url(url),
            "https://mp.weixin.qq.com/s?__biz=MzAwMDYwMTQ4Mg%3D%3D&idx=2&mid=2649470534&sn=abc",
        )

    def test_discover_from_local_profile_reads_history_and_share_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir) / "multitab_e309f1787e0d9b7476197212293241eb" / "Default"
            base.mkdir(parents=True)

            history = base / "History"
            conn = sqlite3.connect(history)
            conn.execute("create table urls (url text, title text, last_visit_time integer)")
            conn.execute(
                "insert into urls values (?, ?, ?)",
                ("https://mp.weixin.qq.com/s/demo-1", "大魔王的后花园", 1),
            )
            conn.commit()
            conn.close()

            share_db = base / "Share Data"
            conn = sqlite3.connect(share_db)
            conn.execute(
                "create table share_data_table (id integer primary key, url text, real_url text, author text, share_data blob, enable_menu_item integer not null default 0)"
            )
            conn.execute(
                "insert into share_data_table (url, real_url, author, share_data) values (?, ?, ?, ?)",
                (
                    "",
                    "",
                    "大魔王的后花园",
                    "https://mp.weixin.qq.com/s?__biz=MzAwMDYwMTQ4Mg==&mid=2649470534&idx=2&sn=9709dd887e85d5203e920d8ff9a3f067&pass_ticket=secret",
                ),
            )
            conn.commit()
            conn.close()

            report = discover_from_local_profile("大魔王的后花园", account_biz="MzAwMDYwMTQ4Mg==", profile_root=tmp_dir)
            self.assertEqual(
                report.urls,
                [
                    "https://mp.weixin.qq.com/s/demo-1",
                    "https://mp.weixin.qq.com/s?__biz=MzAwMDYwMTQ4Mg%3D%3D&idx=2&mid=2649470534&sn=9709dd887e85d5203e920d8ff9a3f067",
                ],
            )
            self.assertTrue(report.sources)

    def test_extract_urls_from_general_msg_list_handles_single_and_multi(self) -> None:
        payload = {
            "general_msg_list": '{"list":[{"app_msg_ext_info":{"content_url":"http://mp.weixin.qq.com/s?__biz=MzAwMDYwMTQ4Mg==&amp;mid=1&amp;idx=1&amp;sn=a#wechat_redirect","multi_app_msg_item_list":[{"content_url":"http://mp.weixin.qq.com/s?__biz=MzAwMDYwMTQ4Mg==&amp;mid=2&amp;idx=1&amp;sn=b#wechat_redirect"}]}}]}'
        }
        self.assertEqual(
            _extract_urls_from_general_msg_list(payload),
            [
                "https://mp.weixin.qq.com/s?__biz=MzAwMDYwMTQ4Mg%3D%3D&idx=1&mid=1&sn=a",
                "https://mp.weixin.qq.com/s?__biz=MzAwMDYwMTQ4Mg%3D%3D&idx=1&mid=2&sn=b",
            ],
        )

    def test_discover_from_profile_ext_uses_seed_and_paginates(self) -> None:
        seed_url = (
            "https://mp.weixin.qq.com/s?__biz=MzAwMDYwMTQ4Mg==&mid=401744893&idx=1&sn=2af8"
            "&scene=126&uin=MjMxMzEzMDQyMA%3D%3D&key=secret-key&pass_ticket=secret-ticket"
        )
        article_html = '<script>var appmsg_token = "token-123";</script>'
        page0 = {
            "ret": 0,
            "can_msg_continue": 1,
            "next_offset": 10,
            "general_msg_list": '{"list":[{"app_msg_ext_info":{"content_url":"http://mp.weixin.qq.com/s?__biz=MzAwMDYwMTQ4Mg==&mid=10&idx=1&sn=aaa","multi_app_msg_item_list":[]}}]}',
        }
        page1 = {
            "ret": 0,
            "can_msg_continue": 0,
            "next_offset": 10,
            "general_msg_list": '{"list":[{"app_msg_ext_info":{"content_url":"http://mp.weixin.qq.com/s?__biz=MzAwMDYwMTQ4Mg==&mid=11&idx=1&sn=bbb","multi_app_msg_item_list":[]}}]}',
        }
        responses = [article_html, json.dumps(page0), json.dumps(page1)]

        def fake_fetch(_url: str, *, headers: dict[str, str] | None = None) -> str:
            return responses.pop(0)

        with patch("obsidian_knowledge_ingestor.wechat_discovery._fetch_text", side_effect=fake_fetch):
            report = discover_from_profile_ext(
                "大魔王的后花园",
                account_biz="MzAwMDYwMTQ4Mg==",
                seed_urls=[seed_url],
                max_pages=5,
            )

        self.assertEqual(
            report.urls,
            [
                "https://mp.weixin.qq.com/s?__biz=MzAwMDYwMTQ4Mg%3D%3D&idx=1&mid=10&sn=aaa",
                "https://mp.weixin.qq.com/s?__biz=MzAwMDYwMTQ4Mg%3D%3D&idx=1&mid=11&sn=bbb",
            ],
        )
        self.assertEqual(report.sources, [seed_url])


if __name__ == "__main__":
    unittest.main()
