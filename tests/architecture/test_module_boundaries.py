# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import arca_public_import as legacy
from src.nai_studio import legacy_app
from src.nai_studio.collection import arca
from src.nai_studio.services.public_collection import PublicCollectionManager


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

    def test_collection_manager_implementation_stays_out_of_legacy_app(self):
        self.assertTrue(
            issubclass(legacy_app.PublicCollectionManager, PublicCollectionManager)
        )
        self.assertIsNot(
            legacy_app.PublicCollectionManager, PublicCollectionManager
        )


class LegacyGrowthBoundaryTests(unittest.TestCase):
    def test_transport_and_template_do_not_grow_back_into_monoliths(self):
        source_path = ROOT / "src" / "nai_studio" / "legacy_app.py"
        source = source_path.read_text(encoding="utf-8")
        # 이미 밖으로 옮긴 책임이 다시 들어오는 것만 막는 감소 전용 상한이다.
        # 다음 구조 추출 때 현재 baseline에 맞춰 함께 낮춘다.
        self.assertLessEqual(len(source.splitlines()), 14_500)

        tree = ast.parse(source)
        sizes = {
            node.name: node.end_lineno - node.lineno + 1
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name in {"do_GET", "do_POST"}
        }
        self.assertLessEqual(sizes["do_GET"], 40)
        self.assertLessEqual(sizes["do_POST"], 40)

        template = (
            ROOT / "src" / "nai_studio" / "web" / "page_template.py"
        ).read_text(encoding="utf-8")
        self.assertLessEqual(len(template), 100_000)
        self.assertNotIn("<style>", template)
        self.assertIn('src="/ui/studio.js"', template)


if __name__ == "__main__":
    unittest.main()
