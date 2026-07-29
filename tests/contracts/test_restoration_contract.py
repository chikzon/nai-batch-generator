# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import unittest

from src.nai_studio.domain.restoration import (
    canonical_restore_item,
    canonical_restore_queue,
    enqueue_restore_items,
    mark_restore_result,
    resume_restore_queue,
    summarize_restore_queue,
)


class RestorationContractTests(unittest.TestCase):
    def test_item_is_stable_lossless_and_input_immutable(self):
        long_prompt = "1girl, " + ("very long prompt, " * 900)
        raw = {
            "source_url": "https://example.invalid/post/1",
            "image_refs": ["https://example.invalid/a.webp", "local:abc.webp"],
            "sha256": "a" * 64,
            "metadata": {
                "prompt": long_prompt,
                "negative_prompt": "bad hand\n" * 300,
                "unknown": {"future": [1, 2, 3]},
            },
            "nai_fields": {"model": "nai-diffusion-4-5-full", "seed": 42},
            "cursor": {"page": 3, "index": 7},
            "date": "2026-07-29T12:00:00+09:00",
            "future_field": {"must": "stay"},
        }
        before = copy.deepcopy(raw)
        first = canonical_restore_item(raw)
        second = canonical_restore_item(copy.deepcopy(raw))
        self.assertEqual(raw, before)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["raw_metadata"]["prompt"], long_prompt)
        self.assertEqual(first["raw_metadata"]["unknown"]["future"], [1, 2, 3])
        self.assertEqual(first["detected_fields"]["seed"], 42)
        self.assertEqual(first["future_field"], {"must": "stay"})
        self.assertEqual(len(first["images"]), 2)

    def test_enqueue_keeps_duplicate_instances_and_tracks_changed_source(self):
        queue = canonical_restore_queue({
            "source": {"kind": "folder", "path": "D:/evidence"},
            "date_range": {"from": "2026-01-01", "to": "2026-07-29"},
        })
        queued = enqueue_restore_items(queue, [
            {
                "source_path": "D:/evidence/a.webp",
                "content_hash": "same",
                "raw_metadata": {"prompt": "A"},
            },
            {
                "source_path": "D:/evidence/copy.webp",
                "content_hash": "same",
                "raw_metadata": {"prompt": "A"},
            },
            {
                "source_path": "D:/evidence/a.webp",
                "content_hash": "changed",
                "raw_metadata": {"prompt": "B"},
            },
        ])
        self.assertEqual(len(queued["items"]), 3)
        first, duplicate, changed = queued["items"]
        self.assertEqual(duplicate["relations"]["duplicate_of"], first["id"])
        self.assertEqual(changed["relations"]["change_from"], first["id"])
        self.assertNotEqual(first["id"], duplicate["id"])

        repeated = enqueue_restore_items(queued, [{
            "source_path": "D:/evidence/a.webp",
            "content_hash": "same",
        }])
        self.assertEqual(len(repeated["items"]), 4)
        self.assertEqual(repeated["items"][-1]["relations"]["duplicate_of"], first["id"])
        self.assertEqual(len({item["id"] for item in repeated["items"]}), 4)

    def test_mark_result_preserves_raw_metadata_and_records_candidate(self):
        queue = enqueue_restore_items({}, [{
            "source_url": "https://example.invalid/a",
            "raw_metadata": {"prompt": "1.2::original::"},
        }])
        item_id = queue["items"][0]["id"]
        before = copy.deepcopy(queue)
        marked = mark_restore_result(
            queue,
            item_id,
            "recognized",
            evidence_ref={"id": "evidence:1"},
            blueprint_candidate={
                "style": {"base": "1.2::original::"},
                "future": {"kept": True},
            },
        )
        self.assertEqual(queue, before)
        item = marked["items"][0]
        self.assertEqual(item["recognition"]["status"], "recognized")
        self.assertEqual(item["recognition"]["attempts"], 1)
        self.assertEqual(item["raw_metadata"]["prompt"], "1.2::original::")
        self.assertEqual(
            item["result"]["blueprint_candidate"]["future"],
            {"kept": True},
        )

    def test_failure_retry_resume_preserves_history_cursor_and_other_results(self):
        queue = enqueue_restore_items({
            "status": "stopped",
            "cursor": {"page": 9},
        }, [
            {"source_url": "https://example.invalid/1"},
            {"source_url": "https://example.invalid/2"},
            {"source_url": "https://example.invalid/3"},
        ])
        first, second, third = [item["id"] for item in queue["items"]]
        queue = mark_restore_result(queue, first, "recognized")
        queue = mark_restore_result(queue, second, "unrecognized")
        queue = mark_restore_result(
            queue, third, "failed", error={"code": "temporary"}
        )
        resumed = resume_restore_queue(
            queue,
            cursor={"page": 9, "index": 2},
            retry_failed=True,
        )
        self.assertEqual(resumed["status"], "running")
        self.assertEqual(resumed["cursor"], {"page": 9, "index": 2})
        statuses = [
            item["recognition"]["status"] for item in resumed["items"]
        ]
        self.assertEqual(statuses, ["recognized", "unrecognized", "pending"])
        failed = resumed["items"][2]["recognition"]
        self.assertEqual(failed["attempts"], 1)
        self.assertEqual(failed["history"][0]["error"]["code"], "temporary")

    def test_summary_counts_many_images_relations_and_dates(self):
        queue = enqueue_restore_items({
            "source": {"kind": "post-range"},
            "date_range": {"from": "2026-07-01", "to": "2026-07-29"},
            "cursor": {"date": "2026-07-15", "post": 30},
        }, [
            {
                "source_url": "https://example.invalid/1",
                "images": ["1.webp", "2.webp"],
                "content_hash": "one",
            },
            {
                "source_url": "https://example.invalid/2",
                "images": ["3.webp"],
                "content_hash": "one",
            },
        ])
        queue = mark_restore_result(
            queue, queue["items"][0]["id"], "recognized"
        )
        summary = summarize_restore_queue(queue)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["images"], 3)
        self.assertEqual(summary["recognized"], 1)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["duplicates"], 1)
        self.assertEqual(
            summary["date_range"],
            {"from": "2026-07-01", "to": "2026-07-29"},
        )
        self.assertEqual(summary["cursor"]["post"], 30)

    def test_invalid_status_and_missing_item_fail_explicitly(self):
        with self.assertRaises(ValueError):
            mark_restore_result({}, "missing", "pending")
        with self.assertRaises(KeyError):
            mark_restore_result({}, "missing", "recognized")


if __name__ == "__main__":
    unittest.main()
