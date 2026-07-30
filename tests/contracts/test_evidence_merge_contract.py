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


if __name__ == "__main__":
    unittest.main()
