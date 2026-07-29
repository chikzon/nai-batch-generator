# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import unittest

from src.nai_studio.services.legacy_bridge import (
    character_asset_from_record,
    evidence_from_image_record,
    evaluations_from_picks,
    knowledge_assets_from_config,
    restoration_queue_from_collection,
    sequence_plan_from_setting,
    setting_asset_from_record,
    style_asset_from_record,
)


class LegacyBridgeContractTests(unittest.TestCase):
    def test_image_evidence_preserves_raw_and_long_generation_values(self):
        base = "1.2::artist:test::, " + ("가나다\n{a|b}, " * 900)
        record = {
            "title": "원본",
            "source": "공유 자료",
            "url": "https://example.invalid/original",
            "images": ["local:abc.webp"],
            "base": base,
            "negative_full": "bad anatomy\n" * 700,
            "characters": [{"prompt": "c" * 5000, "negative": "n" * 4000}],
            "params": {"cfg_scale": 5.5, "seed": 123},
            "metadata_raw": {"Comment": {"prompt": base}},
        }
        before = copy.deepcopy(record)
        evidence = evidence_from_image_record(record)
        self.assertEqual(evidence["actual_generation"]["base"], base)
        self.assertEqual(
            evidence["raw_metadata"]["Comment"]["prompt"],
            base,
        )
        self.assertEqual(record, before)

    def test_style_bundle_stays_indivisible(self):
        asset = style_asset_from_record({
            "name": "묶음",
            "base": "base",
            "negative": "negative",
            "params": {"cfg_scale": 6.0, "sampler": "k_euler"},
        })
        self.assertEqual(asset["content"]["base"], "base")
        self.assertEqual(asset["content"]["negative"], "negative")
        self.assertEqual(asset["content"]["generation_settings"]["cfg_scale"], 6.0)

    def test_character_keeps_outfit_variant_and_refs(self):
        asset = character_asset_from_record({
            "name": "캐릭터",
            "female": "appearance",
            "clothed": "artistic variation and outfit",
            "negative": "character negative",
            "variant": {"group": "A", "name": "winter"},
            "reference_ids": ["ref-1"],
            "vibe_ids": ["vibe-1"],
        })
        content = asset["content"]
        self.assertEqual(content["prompt"], "appearance")
        self.assertEqual(content["clothed"], "artistic variation and outfit")
        self.assertEqual(content["negative"], "character negative")
        self.assertEqual(content["variants"][0]["name"], "winter")
        self.assertEqual(content["reference_refs"], ["ref-1"])
        self.assertEqual(content["vibe_refs"], ["vibe-1"])

    def test_setting_projection_keeps_plan_material(self):
        asset = setting_asset_from_record({
            "name": "장면",
            "씬": {"첫 장": {"prompt": "scene"}},
            "관계": [{"from": "a", "to": "b"}],
            "위치": [{"x": 0.13, "y": 0.87}],
            "옵션": {"fixed_seed": True},
            "단계": ["first", "last"],
        })
        content = asset["content"]
        self.assertEqual(content["scenes"][0]["prompt"], "scene")
        self.assertEqual(content["positions"][0]["x"], 0.13)
        self.assertTrue(content["options"]["fixed_seed"])

    def test_current_config_projects_without_token(self):
        assets = knowledge_assets_from_config({
            "token": "must-not-cross",
            "base_prompt": "base",
            "negative_prompt": "neg",
            "cfg_scale": 5.5,
            "characters": [{"name": "C", "female": "girl"}],
        })
        text = repr(assets)
        self.assertEqual(len(assets), 2)
        self.assertNotIn("must-not-cross", text)

    def test_existing_picks_project_to_common_evaluations(self):
        evaluations = evaluations_from_picks({
            "picked": ["output/a.webp"],
            "fav": ["output/a.webp"],
            "folders": {"고정 비교판": ["output/a.webp"]},
            "ratings": {"output/a.webp": 5},
            "elo": {"output/a.webp": 1612.5},
            "elo_matches": {"output/a.webp": 7},
            "tags": {"output/a.webp": ["선명", "구도"]},
        })
        self.assertEqual(len(evaluations), 1)
        evaluation = evaluations[0]
        self.assertTrue(evaluation["favorite"])
        self.assertEqual(evaluation["rating"], 5)
        self.assertEqual(evaluation["fixed_board"]["boards"], ["고정 비교판"])
        self.assertEqual(evaluation["elo"]["rating"], 1612.5)
        self.assertEqual(evaluation["blind"]["matches"], 7)
        self.assertEqual(evaluation["result_refs"], ["result:output/a.webp"])

    def test_public_collection_projects_to_restore_queue_without_loss(self):
        queue = restoration_queue_from_collection({
            "schema": "nais-public-collection/v2",
            "status": "paused",
            "keyword": "그림체",
            "cursor": 1,
            "queue": ["https://example.invalid/a", "https://example.invalid/b"],
            "articles": {
                "https://example.invalid/a": {
                    "title": "A", "digest": "a" * 64,
                    "image_urls": ["https://example.invalid/a.png"],
                    "metadata_images": 1,
                },
            },
            "failures": {
                "https://example.invalid/b": {
                    "title": "B", "attempts": 2, "error": "timeout",
                },
            },
        })
        self.assertEqual(queue["status"], "paused")
        self.assertEqual(queue["cursor"], 1)
        self.assertEqual(len(queue["items"]), 2)
        self.assertEqual(
            queue["items"][0]["recognition"]["status"], "recognized")
        self.assertEqual(
            queue["items"][1]["recognition"]["status"], "failed")
        self.assertEqual(
            queue["items"][1]["recognition"]["error"], "timeout")

    def test_existing_setting_projects_to_sequence_without_conversion(self):
        raw = {
            "이름": "연속 장면",
            "방식": "단독",
            "옵션": {
                "freeze_characters": True,
                "freeze_wildcards": True,
            },
            "단계명": ["도입", "마무리"],
            "씬": {
                "101": {
                    "name": "도입", "female_prompt": "long prompt",
                    "negative_prompt": "negative", "width": 832,
                    "height": 1216, "background": "room",
                    "future_scene_field": {"keep": True},
                },
                "102": {
                    "name": "마무리", "female_prompt": "second",
                    "carry": {"background": True},
                    "vibe_continuity": {"source": "previous"},
                },
            },
        }
        before = copy.deepcopy(raw)
        plan = sequence_plan_from_setting(raw)
        self.assertEqual(plan["order"], ["scene-101", "scene-102"])
        self.assertTrue(plan["freeze"]["characters"])
        self.assertTrue(plan["freeze"]["wildcards"])
        self.assertEqual(plan["steps"][0]["resolution"]["width"], 832)
        self.assertEqual(
            plan["steps"][0]["legacy_scene"]["future_scene_field"],
            {"keep": True},
        )
        self.assertTrue(plan["steps"][1]["carry"]["background"])
        self.assertEqual(
            plan["steps"][1]["vibe_continuity"]["source"], "previous")
        self.assertEqual(raw, before)


if __name__ == "__main__":
    unittest.main()
