from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from obsidian_knowledge_ingestor.wechat_discovery import discover_from_local_profile, normalize_article_url


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


if __name__ == "__main__":
    unittest.main()
