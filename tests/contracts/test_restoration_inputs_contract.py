# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
import unittest

from src.nai_studio.services.restoration_inputs import (
    folder_inventory_summary,
    folder_inventory_queue,
    image_batch_queue,
    image_inspect_queue,
    pack_import_queue,
    public_collection_queue,
    public_collection_summary,
    restoration_queue_from_input,
    retry_restoration_inputs,
)


TOKEN = "pst-ne-example-secret-that-must-never-cross"


class RestorationInputsContractTests(unittest.TestCase):
    def assert_safe_contract(self, value):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn(r"C:\Users\private", text)
        self.assertNotIn("89504e470d0a", text)
        return text

    def test_single_inspect_keeps_full_metadata_and_generation_without_binary(self):
        prompt = "1.2::artist:test::, " + ("긴 프롬프트\n" * 1200)
        raw = {
            "ok": True,
            "style": {
                "id": "file-one",
                "title": "원본",
                "base": prompt,
                "negative_full": "negative\n" * 800,
                "characters": [{"prompt": "character" * 500}],
                "params": {"seed": 42, "cfg_scale": 5.5},
                "metadata_raw": {
                    "Comment": {"prompt": prompt},
                    "token": TOKEN,
                    "source_path": r"C:\Users\private\original.png",
                    "image_bytes": b"\x89PNG\r\n",
                },
                "images": ["local:abc.webp"],
                "content_sha256": "a" * 64,
            },
        }
        before = copy.deepcopy(raw)
        queue = image_inspect_queue(
            raw,
            filename=r"C:\Users\private\original.png",
            source_url=(
                "https://user:password@example.invalid/post/1?token="
                + TOKEN
                + "&view=full#private"
            ),
        )
        self.assertEqual(raw, before)
        self.assertEqual(queue["status"], "completed")
        item = queue["items"][0]
        evidence = item["result"]["evidence_candidate"]
        self.assertEqual(evidence["actual_generation"]["base"], prompt)
        self.assertEqual(
            evidence["raw_metadata"]["Comment"]["prompt"],
            prompt,
        )
        self.assertEqual(evidence["image"]["filename"], "original.png")
        self.assertEqual(
            evidence["source"]["url"],
            "https://example.invalid/post/1?view=full",
        )
        self.assertEqual(item["recognition"]["status"], "recognized")
        self.assert_safe_contract(queue)

    def test_multi_image_tracks_duplicate_and_changed_source_without_path(self):
        rows = [
            {
                "ok": True,
                "filename": r"C:\Users\private\a.png",
                "path": r"C:\Users\private\a.png",
                "content_hash": "same",
                "base": "A",
            },
            {
                "ok": True,
                "filename": r"C:\Users\private\copy.png",
                "path": r"C:\Users\private\copy.png",
                "content_hash": "same",
                "base": "A",
            },
            {
                "ok": True,
                "filename": r"C:\Users\private\a.png",
                "path": r"C:\Users\private\a.png",
                "content_hash": "changed",
                "base": "B",
            },
        ]
        queue = image_batch_queue(rows, cursor={"index": 2}, status="paused")
        first, duplicate, changed = queue["items"]
        self.assertEqual(duplicate["relations"]["duplicate_of"], first["id"])
        self.assertEqual(changed["relations"]["change_from"], first["id"])
        self.assertEqual(queue["cursor"], {"index": 2})
        self.assertEqual(
            changed["result"]["evidence_candidate"]["actual_generation"]["base"],
            "B",
        )
        self.assert_safe_contract(queue)

    def test_public_collection_keeps_dates_cursor_pause_and_failure_retry(self):
        state = {
            "schema": "nais-public-collection/v2",
            "status": "paused",
            "stage": "paused",
            "keyword": "그림체",
            "date_range": {"from": "2026-07-01", "to": "2026-07-29"},
            "cursor": 1,
            "queue": [
                "https://example.invalid/a",
                "https://example.invalid/b",
            ],
            "articles": {
                "https://example.invalid/a": {
                    "posted_at": "2026-07-01T12:00:00+09:00",
                    "image_urls": ["https://example.invalid/a.png"],
                    "metadata_images": 1,
                    "digest": "a" * 64,
                    "metadata_raw": {"prompt": "A"},
                },
            },
            "failures": {
                "https://example.invalid/b": {
                    "attempts": 2,
                    "error": "timeout at C:\\Users\\private\\cache",
                    "history": [{"attempt": 1, "token": TOKEN}],
                },
            },
        }
        queue = public_collection_queue(state)
        self.assertEqual(queue["status"], "paused")
        self.assertEqual(queue["cursor"], 1)
        self.assertEqual(
            queue["date_range"],
            {"from": "2026-07-01", "to": "2026-07-29"},
        )
        self.assertEqual(
            [item["recognition"]["status"] for item in queue["items"]],
            ["recognized", "failed"],
        )
        failed = queue["items"][1]
        retried = retry_restoration_inputs(
            queue,
            item_ids=[failed["id"]],
            cursor=1,
        )
        self.assertEqual(retried["status"], "running")
        self.assertEqual(
            retried["items"][1]["recognition"]["status"],
            "pending",
        )
        self.assertEqual(
            retried["items"][1]["recognition"]["attempts"],
            2,
        )
        self.assert_safe_contract(retried)

    def test_public_collection_includes_history_and_scrubs_key_variants_and_posix_paths(self):
        state = {
            "status": "idle",
            "queue": ["https://example.invalid/current"],
            "articles": {
                "https://example.invalid/history": {
                    "metadata_images": 1,
                    "metadata_raw": {
                        "access_token": "opaque-secret",
                        "naiToken": "also-secret",
                        "note": "cached at /home/private/file.png",
                    },
                },
            },
            "failures": {
                "https://example.invalid/failed-history": {
                    "error": "read /tmp/private/cache.webp",
                    "attempts": 1,
                },
            },
        }
        queue = public_collection_queue(state)
        self.assertEqual(len(queue["items"]), 3)
        text = json.dumps(queue, ensure_ascii=False)
        self.assertNotIn("opaque-secret", text)
        self.assertNotIn("also-secret", text)
        self.assertNotIn("/home/private", text)
        self.assertNotIn("/tmp/private", text)

    def test_polling_summaries_do_not_materialize_items_or_claim_folder_metadata(self):
        state = {
            "status": "paused",
            "queue": ["https://example.invalid/current"],
            "articles": {
                "https://example.invalid/history": {
                    "metadata_images": 2,
                    "image_count": 3,
                },
            },
            "failures": {
                "https://example.invalid/failed": {"attempts": 1},
            },
            "cursor": 1,
        }
        summary = public_collection_summary(state)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["recognized"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["pending"], 1)
        self.assertNotIn("items", summary)
        inventory = folder_inventory_summary({
            "files": 10000,
            "fingerprint": "a" * 64,
        })
        self.assertEqual(inventory["pending"], 10000)
        self.assertEqual(inventory["recognized"], 0)
        self.assertTrue(inventory["inventory_only"])

    def test_pack_import_keeps_manifest_lineage_and_report_without_archive(self):
        result = {
            "ok": True,
            "added": 37,
            "batch": "batch-1",
            "report": ["그림체 37건"],
            "manifest": {
                "id": "public-pack",
                "name": "공개 자료",
                "version": "2",
                "content_sha256": "b" * 64,
                "token": TOKEN,
            },
            "batch_record": {
                "id": "batch-1",
                "file": r"C:\Users\private\pack.zip",
                "archive_sha256": "b" * 64,
                "installed": ["수집/그림체.json"],
                "body": bytes.fromhex("89504e470d0a"),
            },
        }
        queue = pack_import_queue(
            result,
            filename=r"C:\Users\private\pack.zip",
        )
        item = queue["items"][0]
        self.assertEqual(item["content_hash"], "b" * 64)
        self.assertEqual(item["source"]["source_id"], "public-pack")
        metadata = item["raw_metadata"]
        self.assertEqual(metadata["report"], ["그림체 37건"])
        self.assertEqual(metadata["added"], 37)
        self.assertEqual(metadata["batch"], "batch-1")
        self.assert_safe_contract(queue)

    def test_pack_import_accepts_actual_brief_log_shape(self):
        queue = pack_import_queue({
            "ok": True,
            "batch": "batch-2",
            "report": [],
            "log": [
                {
                    "id": "batch-2",
                    "file": "pack.zip",
                    "pack_id": "pack-from-brief",
                    "pack_name": "간략 기록",
                    "content_sha256": "c" * 64,
                },
            ],
        })
        item = queue["items"][0]
        self.assertEqual(item["source"]["source_id"], "pack-from-brief")
        self.assertEqual(item["content_hash"], "c" * 64)

    def test_folder_inventory_keeps_file_metadata_and_change_lineage(self):
        rows = [
            {
                "path": r"C:\Users\private\collection\a.webp",
                "sha256": "first",
                "metadata": {"prompt": "first"},
                "status": "recognized",
            },
            {
                "path": r"C:\Users\private\collection\a.webp",
                "sha256": "second",
                "metadata": {"prompt": "second"},
                "status": "recognized",
            },
            {
                "path": r"C:\Users\private\collection\b.webp",
                "sha256": "second",
                "metadata": {"prompt": "second"},
                "status": "recognized",
            },
        ]
        before = copy.deepcopy(rows)
        queue = folder_inventory_queue(
            rows,
            folder_label="보유 자료",
            cursor={"file": 2},
            status="interrupted",
        )
        self.assertEqual(rows, before)
        first, changed, duplicate = queue["items"]
        self.assertEqual(changed["relations"]["change_from"], first["id"])
        self.assertEqual(
            duplicate["relations"]["duplicate_of"],
            changed["id"],
        )
        self.assertTrue(
            first["source"]["source_id"].startswith("path-sha256:")
        )
        self.assertEqual(first["source"]["filename"], "a.webp")
        self.assertEqual(queue["cursor"], {"file": 2})
        self.assert_safe_contract(queue)

    def test_folder_inventory_accepts_plain_path_entries_without_leaking_them(self):
        queue = folder_inventory_queue([
            r"C:\Users\private\collection\plain.webp",
        ])
        item = queue["items"][0]
        self.assertEqual(item["source"]["filename"], "plain.webp")
        self.assertTrue(item["source"]["source_id"].startswith("path-sha256:"))
        self.assert_safe_contract(queue)

    def test_dispatcher_supports_all_input_families_and_rejects_unknown(self):
        cases = [
            ("image", {"ok": True, "style": {"base": "A"}}),
            ("images", [{"ok": True, "base": "A"}]),
            ("collection", {"queue": []}),
            ("pack", {"ok": True, "batch": "one"}),
            ("folder", [{"path": "relative/a.webp"}]),
        ]
        for kind, payload in cases:
            with self.subTest(kind=kind):
                queue = restoration_queue_from_input(kind, payload)
                self.assertEqual(
                    queue["metadata"]["schema"],
                    "nai-restoration-input/v1",
                )
                self.assert_safe_contract(queue)
        with self.assertRaises(ValueError):
            restoration_queue_from_input("unknown", {})


if __name__ == "__main__":
    unittest.main()
