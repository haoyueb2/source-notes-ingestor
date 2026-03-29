from __future__ import annotations

import unittest

from source_notes_ingestor.verification import _build_checks, _profile_text_counts


class VerificationTests(unittest.TestCase):
    def test_profile_text_counts_extracts_tab_totals(self) -> None:
        text = "动态 回答27 视频0 提问0 文章3 专栏0 想法60 收藏14"
        self.assertEqual(
            _profile_text_counts(text),
            {"answers": 27, "articles": 3, "thoughts": 60},
        )

    def test_checks_warn_when_profile_and_accessible_differ_but_library_matches_accessible(self) -> None:
        checks = _build_checks(
            profile_counts={"answers": 27, "articles": 3, "thoughts": 60},
            accessible_counts={"answers": 26, "articles": 3, "thoughts": 60},
            library_counts={"answers": 26, "articles": 3, "thoughts": 60},
        )
        self.assertEqual(checks["answers"].status, "warn")
        self.assertEqual(checks["articles"].status, "pass")
        self.assertIn("profile shows 27 but accessible list exposes 26", checks["answers"].note)


if __name__ == "__main__":
    unittest.main()
