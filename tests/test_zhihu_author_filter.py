from pathlib import Path
import unittest

from obsidian_knowledge_ingestor.adapters.zhihu import fetch_source


class ZhihuAuthorFilterTests(unittest.TestCase):
    def test_filters_out_answer_from_another_author(self) -> None:
        html_path = Path('/Users/haoyuebai/Dev/ai/obsidian-knowledge-ingestor/samples/zhihu/lin-lin-98-23/2196379477.html')
        items = fetch_source(
            {
                'author_id': 'lin-lin-98-23',
                'author_name': 'lin-lin-98-23',
                'html_paths': [str(html_path)],
                'base_url': 'https://www.zhihu.com/question/492888437/answer/2196379477',
            },
            auth_ctx=None,
            since=None,
        )
        self.assertEqual(items, [])

    def test_keeps_pin_from_target_author(self) -> None:
        html_path = Path('/Users/haoyuebai/Dev/ai/obsidian-knowledge-ingestor/samples/zhihu/lin-lin-98-23/1445199313127813120.html')
        items = fetch_source(
            {
                'author_id': 'lin-lin-98-23',
                'author_name': 'lin-lin-98-23',
                'html_paths': [str(html_path)],
                'base_url': 'https://www.zhihu.com/pin/1445199313127813120',
            },
            auth_ctx=None,
            since=None,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].content_type, 'thought')
        self.assertEqual(items[0].content_id, '1445199313127813120')


if __name__ == '__main__':
    unittest.main()
