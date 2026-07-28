# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import arca_public_import as legacy
from src.nai_studio.collection import arca


class PublicCollectionBoundaryTests(unittest.TestCase):
    def test_legacy_import_reexports_same_public_objects(self):
        names = (
            "ARCA_BASE_URL",
            "ARCA_BOARD_PATH",
            "DEFAULT_KEYWORD",
            "PublicImportError",
            "normalize_article_url",
            "build_search_url",
            "extract_search_results",
            "extract_article",
            "create_session",
            "fetch_text",
            "fetch_image",
        )
        for name in names:
            self.assertIs(getattr(legacy, name), getattr(arca, name), name)

    def test_legacy_import_keeps_private_helpers_available(self):
        self.assertIs(legacy._safe_url, arca._safe_url)
        self.assertIs(legacy._ArticleParser, arca._ArticleParser)

    def test_normalization_behavior_is_unchanged_through_adapter(self):
        value = "https://arca.live/b/aiart/158674617?mode=best"
        self.assertEqual(
            legacy.normalize_article_url(value),
            arca.normalize_article_url(value),
        )


if __name__ == "__main__":
    unittest.main()
