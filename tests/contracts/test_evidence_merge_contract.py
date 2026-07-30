# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.nai_studio.services.evidence_merge import (  # noqa: E402
    dupe_compare_payload,
    merge_evidence_rows,
    prompt_segment_diff,
    prompt_segments,
)


def _digest(row) -> str:
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


STYLE_A = {
    "id": "style-a",
    "title": "그림체 A",
    "prompt": "1.7::artist:inoue kiyoshirou::, 0.8::artist:freng::, 1girl",
    "negative": "lowres, bad hands",
    "settings": {"cfg_scale": 6.2, "steps": 28},
    "source": "아카",
    "url": "https://arca.live/b/aiart/1",
    "images": ["local:aaa.webp"],
    "evidence": [{"title": "원본 A"}],
    "evidence_records": [{"id": "ev-1"}],
}
STYLE_B = {
    "id": "style-b",
    "title": "그림체 B",
    "prompt": "0.8::artist:freng::, 1girl, watercolor (medium)",
    "negative": "lowres",
    "settings": {"cfg_scale": 6.2, "steps": 28},
    "source": "아카",
    "url": "https://arca.live/b/aiart/2",
    "images": ["local:bbb.webp"],
    "evidence": [{"title": "원본 B"}],
    "evidence_records": [{"id": "ev-2"}],
}


class PromptSegmentContractTests(unittest.TestCase):
    def test_weight_group_commas_do_not_split_segments(self):
        text = "0.6::artist:a, artist:b::, 1girl, {smile|laugh}"
        segments = prompt_segments(text)
        self.assertEqual(segments, [
            "0.6::artist:a, artist:b::",
            "1girl",
            "{smile|laugh}",
        ])

    def test_diff_keeps_original_text_and_orders(self):
        diff = prompt_segment_diff(STYLE_A["prompt"], STYLE_B["prompt"])
        self.assertEqual(diff["common"], [
            "0.8::artist:freng::",
            "1girl",
        ])
        self.assertEqual(diff["left_only"], [
            "1.7::artist:inoue kiyoshirou::",
        ])
        self.assertEqual(diff["right_only"], ["watercolor (medium)"])

    def test_weight_change_is_not_reported_as_common(self):
        diff = prompt_segment_diff("1.2::artist:x::", "0.5::artist:x::")
        self.assertEqual(diff["common"], [])
        self.assertEqual(diff["left_only"], ["1.2::artist:x::"])
        self.assertEqual(diff["right_only"], ["0.5::artist:x::"])

    def test_parentheses_tags_survive_untouched(self):
        segments = prompt_segments("2b (nier:automata), 1920s (style)")
        self.assertEqual(
            segments, ["2b (nier:automata)", "1920s (style)"])


class DupeCompareContractTests(unittest.TestCase):
    def payload(self, ids):
        return dupe_compare_payload(
            [dict(STYLE_A), dict(STYLE_B)],
            ids,
            canonical_settings=lambda record: dict(
                record.get("settings") or {}),
            rating_for=lambda record: {"score": 4},
        )

    def test_side_by_side_rows_carry_all_review_material(self):
        payload = self.payload(["style-a", "style-b"])
        self.assertTrue(payload["ok"])
        row = payload["rows"][0]
        for key in (
            "prompt", "negative", "settings", "images",
            "source", "url", "evidence", "evidence_records", "rating",
        ):
            self.assertIn(key, row)
        self.assertEqual(
            payload["prompt_diff"]["right_only"], ["watercolor (medium)"])
        self.assertEqual(
            payload["negative_diff"]["left_only"], ["bad hands"])

    def test_unknown_or_single_selection_is_rejected(self):
        self.assertFalse(self.payload(["style-a"])["ok"])
        self.assertFalse(self.payload(["style-a", "없는것"])["ok"])


class EvidenceMergeContractTests(unittest.TestCase):
    def test_merge_adds_evidence_without_deleting_originals(self):
        rows = [dict(STYLE_A), dict(STYLE_B)]
        result = merge_evidence_rows(
            rows, "style-a", ["style-b"], row_digest=_digest)
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        merged_rows = result["rows"]
        self.assertEqual(len(merged_rows), 2)  # 원본 자산은 남는다
        representative = merged_rows[0]
        self.assertEqual(representative["id"], "style-a")
        # 원문·설정은 그대로, 증거만 늘었다
        self.assertEqual(representative["prompt"], STYLE_A["prompt"])
        self.assertIn("local:bbb.webp", representative["images"])
        self.assertEqual(
            [item["id"] for item in representative["evidence_records"]],
            ["ev-1", "ev-2"])
        batch = result["batch"]
        self.assertEqual(batch["kind"], "evidence-merge")
        update = batch["list_updates"][0]
        self.assertEqual(update["stem"], "그림체.json")
        self.assertEqual(update["key"], "style-a")
        self.assertEqual(update["before"], STYLE_A)
        self.assertEqual(update["after_sha256"], _digest(representative))

    def test_second_merge_of_same_other_is_idempotent(self):
        rows = [dict(STYLE_A), dict(STYLE_B)]
        first = merge_evidence_rows(
            rows, "style-a", ["style-b"], row_digest=_digest)
        self.assertTrue(first["changed"])
        second = merge_evidence_rows(
            first["rows"], "style-a", ["style-b"], row_digest=_digest)
        self.assertTrue(second["ok"])
        self.assertFalse(second["changed"])
        self.assertIsNone(second["batch"])

    def test_missing_ids_are_rejected(self):
        rows = [dict(STYLE_A)]
        self.assertFalse(merge_evidence_rows(
            rows, "style-a", ["없는것"], row_digest=_digest)["ok"])
        self.assertFalse(merge_evidence_rows(
            rows, "없는것", ["style-a"], row_digest=_digest)["ok"])
        self.assertFalse(merge_evidence_rows(
            rows, "style-a", [], row_digest=_digest)["ok"])


def _bundle_signature(record: dict) -> str:
    return json.dumps({
        "prompt": record.get("female") or record.get("prompt") or "",
        "outfit": record.get("clothed") or record.get("outfit") or "",
        "negative": record.get("negative") or "",
        "variants": record.get("variants") or [],
        "reference_ids": record.get("reference_ids") or [],
        "vibe_ids": record.get("vibe_ids") or [],
    }, ensure_ascii=False, sort_keys=True)


CHAR_A = {
    "id": "char-a",
    "name": "세렌",
    "female": "1girl, blue hair",
    "clothed": "navy cloak",
    "negative": "lowres",
    "variants": [{"id": "v1", "outfit": "swimsuit"}],
    "reference_ids": ["ref-1"],
    "vibe_ids": [],
    "evidence_records": [{"id": "ev-a"}],
    "evaluation": {
        "subject": {"kind": "result", "path": "a.png"},
        "rating": 4,
        "favorite": False,
        "tags": ["파랑"],
    },
}
CHAR_B = {
    "id": "char-b",
    "name": "세렌 사본",
    "female": "1girl, blue hair",
    "clothed": "navy cloak",
    "negative": "lowres",
    "variants": [{"id": "v2", "outfit": "dress"}],
    "reference_ids": ["ref-2"],
    "vibe_ids": ["vibe-1"],
    "evidence_records": [{"id": "ev-b"}],
    "evaluation": {
        "subject": {"kind": "result", "path": "a.png"},
        "rating": 5,
        "favorite": True,
        "tags": ["망토"],
    },
}


class CharacterDupeContractTests(unittest.TestCase):
    def test_same_bundle_signature_groups_together(self):
        from src.nai_studio.services.evidence_merge import (
            find_character_dupes,
        )

        other = dict(CHAR_A) | {"id": "char-c", "female": "1girl, red hair"}
        result = find_character_dupes(
            [dict(CHAR_A), dict(CHAR_B), other],
            bundle_signature=_bundle_signature,
        )
        self.assertTrue(result["ok"])
        # A·B는 변형·참조가 달라 같은 묶음이 아니다 — 지문 함수 기준 그대로
        self.assertEqual(result["묶음"], 0)
        twins = find_character_dupes(
            [dict(CHAR_A), dict(CHAR_A) | {"id": "char-c", "name": "쌍둥이"}],
            bundle_signature=_bundle_signature,
        )
        self.assertEqual(twins["묶음"], 1)
        self.assertEqual(twins["목록"][0]["건수"], 2)

    def test_compare_payload_carries_bundles_and_diff(self):
        from src.nai_studio.services.evidence_merge import (
            character_compare_payload,
        )

        payload = character_compare_payload(
            [dict(CHAR_A), dict(CHAR_B)],
            ["char-a", "char-b"],
            bundle_signature=_bundle_signature,
        )
        self.assertTrue(payload["ok"])
        row = payload["rows"][0]
        for key in ("prompt", "outfit", "negative", "variants",
                    "reference_ids", "vibe_ids", "bundle_signature"):
            self.assertIn(key, row)
        self.assertEqual(payload["prompt_diff"]["left_only"], [])


class CharacterMergeContractTests(unittest.TestCase):
    def merge(self, resource_records=None):
        from src.nai_studio.services.evidence_merge import (
            merge_character_assets,
        )

        return merge_character_assets(
            [dict(CHAR_A), dict(CHAR_B)],
            "char-a",
            ["char-b"],
            bundle_signature=_bundle_signature,
            resource_records=resource_records or [],
        )

    def test_merge_adds_only_and_keeps_originals(self):
        result = self.merge()
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["changed"])
        rows = result["rows"]
        self.assertEqual(len(rows), 2)  # 원본 캐릭터는 남는다
        merged = rows[0]
        # 원문은 대표 것 그대로
        self.assertEqual(merged["female"], CHAR_A["female"])
        # 변형·참조·증거는 합집합
        self.assertEqual(
            [v["id"] for v in merged["variants"]], ["v1", "v2"])
        self.assertEqual(sorted(merged["reference_ids"]), ["ref-1", "ref-2"])
        self.assertEqual(merged["vibe_ids"], ["vibe-1"])
        self.assertEqual(
            [e["id"] for e in merged["evidence_records"]], ["ev-a", "ev-b"])
        # 원본 B는 무변경
        self.assertEqual(rows[1]["variants"], CHAR_B["variants"])

    def test_evaluations_are_merged_via_domain_rules(self):
        result = self.merge()
        evaluation = result["rows"][0]["evaluation"]
        self.assertTrue(evaluation["favorite"])  # any()
        self.assertEqual(sorted(evaluation["tags"]), ["망토", "파랑"])

    def test_duplicate_resources_are_reported_not_auto_merged(self):
        same_image = {"image_ref": "local:same.png"}
        resources = [
            {"id": "ref-1", "kind": "character-reference", **same_image},
            {"id": "ref-2", "kind": "character-reference", **same_image},
            {"id": "vibe-1", "kind": "vibe",
             "image_ref": "local:other.png"},
        ]
        result = self.merge(resource_records=resources)
        self.assertEqual(
            result["resource_duplicates"], [["ref-1", "ref-2"]])

    def test_missing_ids_are_rejected(self):
        from src.nai_studio.services.evidence_merge import (
            merge_character_assets,
        )

        self.assertFalse(merge_character_assets(
            [dict(CHAR_A)], "char-a", ["없는것"],
            bundle_signature=_bundle_signature)["ok"])
        self.assertFalse(merge_character_assets(
            [dict(CHAR_A)], "char-a", [],
            bundle_signature=_bundle_signature)["ok"])


if __name__ == "__main__":
    unittest.main()
