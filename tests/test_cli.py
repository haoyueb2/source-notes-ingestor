import unittest

from obsidian_knowledge_ingestor.cli import build_parser


class CliParserTests(unittest.TestCase):
    def test_cli_is_ingestion_only(self) -> None:
        parser = build_parser()
        commands = parser._subparsers._group_actions[0].choices.keys()
        self.assertEqual(set(commands), {"auth", "ingest", "verify", "discover"})


if __name__ == "__main__":
    unittest.main()
