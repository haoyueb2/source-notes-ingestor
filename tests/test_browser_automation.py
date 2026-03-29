import unittest

from source_notes_ingestor.browser_automation import _extract_links_from_html


class BrowserAutomationTests(unittest.TestCase):
    def test_extract_links_from_html_filters_and_dedupes(self) -> None:
        html = '''
        <html><body>
          <a href="/question/1/answer/2">A1</a>
          <a href="https://www.zhihu.com/question/1/answer/2">A1 dup</a>
          <a href="https://zhuanlan.zhihu.com/p/99">Article</a>
          <a href="https://example.com/ignore">Ignore</a>
        </body></html>
        '''
        import re

        links = _extract_links_from_html(
            html,
            "https://www.zhihu.com/people/demo/answers",
            [re.compile(r"zhihu\.com/question/.+/answer/"), re.compile(r"zhuanlan\.zhihu\.com/p/")],
        )

        self.assertEqual(
            links,
            [
                "https://www.zhihu.com/question/1/answer/2",
                "https://zhuanlan.zhihu.com/p/99",
            ],
        )


if __name__ == "__main__":
    unittest.main()
