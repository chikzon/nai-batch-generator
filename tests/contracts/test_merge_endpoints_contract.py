# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json  # noqa: E402

from src.nai_studio.web.routes.merge_post import handle_merge_post  # noqa: E402
from src.nai_studio.web.routes.recovery_post import (  # noqa: E402
    RecoveryPostOperations,
)
from src.nai_studio.web.routes.collection_post import (  # noqa: E402
    CollectionPostOperations,
)


class FakeRequest:
    def __init__(self, path: str, headers: dict | None = None):
        self.path = path
        self.headers = headers or {}
        self.sent = None

    def _json(self, payload):
        self.sent = payload


BACKUP_CHANGE = {
    "id": "chg-1",
    "logical": "common/규격.json",
    "pointer": "/steps",
    "file_status": "바뀔 파일",
    "json": True,
    "current_exists": True,
    "incoming_exists": True,
    "current": 28,
    "incoming": 30,
    "current_sha256": "c" * 64,
    "incoming_sha256": "i" * 64,
    "base_sha256": "b" * 64,
    "action": "변경",
    "base_available": True,
    "base": 28,
    "base_found": True,
    "decision": "take-incoming",
}

PACK_CONFLICT = {
    "id": "pk-1",
    "logical": "그림체.json",
    "key": "그림체A",
    "kind": "목록 자산",
    "current": {"id": "그림체A", "prompt": "old"},
    "incoming": {"id": "그림체A", "prompt": "new"},
    "current_sha256": "c" * 64,
    "incoming_sha256": "i" * 64,
}


def make_application() -> SimpleNamespace:
    app = SimpleNamespace(
        backup_preview_blob=None,
        backup_preview_sha256="",
        pack_preview_blob=None,
        pack_preview_sha256="",
        pack_preview_filename="",
        cfg={},
        spec={},
        config_revision=0,
        config_lock=threading.RLock(),
    )
    app.use_latest_config = lambda: None
    return app


def recovery_ops(restore_log: list) -> RecoveryPostOperations:
    return RecoveryPostOperations(
        preview_backup=lambda body: {
            "ok": True,
            "sha256": "bk-sha",
            "diff_fingerprint": "bk-diff",
            "changes": [dict(BACKUP_CHANGE)],
        },
        restore_backup=lambda blob, sha, selected=None, expected_diff="": (
            restore_log.append((bytes(blob), sha, list(selected or []))),
            {"ok": True, "batch": "B-1", "changed": 1},
        )[1],
        rollback_backup=lambda batch: {"ok": True, "restored": 1, "batch": batch},
        load_settings=lambda: {},
        default_config=lambda: {},
        migrate_selections=lambda cfg: None,
        migrate_slots=lambda cfg: None,
        load_spec=lambda: {},
        options=lambda: {},
        load_options=lambda: {},
        normalize_local_images=None,
        rollback_local_images=None,
        rebuild_data_index=None,
        metadata_control=None,
        metadata_candidate=None,
        metadata_save=None,
        image_batch_queue=None,
        summarize_queue=lambda queue: {},
    )


def collection_ops(import_log: list) -> CollectionPostOperations:
    return CollectionPostOperations(
        preview_pack=lambda body, filename: {
            "ok": True,
            "sha256": "pk-sha",
            "diff_fingerprint": "pk-diff",
            "conflicts": [dict(PACK_CONFLICT)],
        },
        import_pack=lambda blob, filename, **kwargs: (
            import_log.append((bytes(blob), filename, kwargs)),
            {"ok": True, "batch": "PB-1", "restoration_queue": {}},
        )[1],
        pack_queue=lambda *_, **__: {},
        summarize_queue=lambda *_: {},
        forget_caches=lambda: None,
        load_spec=lambda: {},
        options=lambda: {},
        load_options=lambda: {},
        public_start=None,
        public_retry=None,
        public_control=None,
        undo_pack=lambda pack_id, cfg: {"ok": True, "batch": pack_id},
        import_settings=None,
        resource_import=None,
        reference_add=None,
        reference_save=None,
    )


class MergeEndpointContractTests(unittest.TestCase):
    def setUp(self):
        self.application = make_application()
        self.restore_log: list = []
        self.import_log: list = []
        self.evidence_log: list = []
        self.recovery = recovery_ops(self.restore_log)
        self.collection = collection_ops(self.import_log)
        self.merge = SimpleNamespace(
            evidence_compare=lambda ids: {
                "ok": True,
                "source": "library",
                "rows": [{"id": value} for value in ids],
                "prompt_diff": {"common": [], "left_only": [], "right_only": []},
            },
            evidence_merge=lambda representative, others: (
                self.evidence_log.append((representative, list(others))),
                {"ok": True, "changed": True, "batch": "EV-1"},
            )[1],
        )

    def call(self, path: str, body: bytes = b"", headers=None) -> FakeRequest:
        request = FakeRequest(path, headers)
        handled = handle_merge_post(
            request, self.application, self.recovery, self.collection,
            self.merge, body)
        self.assertTrue(handled)
        return request

    def test_non_merge_paths_fall_through(self):
        request = FakeRequest("/api/backup_preview")
        self.assertFalse(handle_merge_post(
            request, self.application, self.recovery, self.collection,
            self.merge, b""))
        self.assertIsNone(request.sent)

    def test_library_compare_and_evidence_merge_round_trip(self):
        request = self.call(
            "/api/merge_preview",
            json.dumps({"ids": ["a", "b"]}).encode("utf-8"),
            {"X-Source": "library"})
        self.assertTrue(request.sent["ok"])
        self.assertEqual(request.sent["source"], "library")
        self.assertEqual(len(request.sent["rows"]), 2)
        request = self.call(
            "/api/merge_apply",
            json.dumps({
                "source": "library",
                "representative": "a",
                "others": ["b"],
            }).encode("utf-8"))
        self.assertTrue(request.sent["ok"])
        self.assertEqual(
            request.sent["undo"], {"source": "library", "id": "EV-1"})
        self.assertEqual(self.evidence_log, [("a", ["b"])])
        undo = self.call(
            "/api/merge_undo",
            json.dumps({"source": "library", "id": "EV-1"}).encode("utf-8"))
        self.assertTrue(undo.sent["ok"])

    def test_backup_preview_projects_unified_rows_with_decision(self):
        request = self.call(
            "/api/merge_preview", b"PK...", {"X-Source": "backup"})
        payload = request.sent
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["source"], "backup")
        row = payload["rows"][0]
        self.assertEqual(row["decision"], "take-incoming")
        self.assertEqual(row["base"], 28)
        self.assertEqual(row["kind"], "기타")
        self.assertEqual(payload["decisions"], {"take-incoming": 1})
        # preview가 원문을 캐시해 apply가 같은 원문만 받도록 한다
        self.assertEqual(self.application.backup_preview_blob, b"PK...")

    def test_datapack_preview_rows_are_two_way_for_now(self):
        request = self.call(
            "/api/merge_preview", b"PK..",
            {"X-Source": "datapack", "X-Filename": "팩.zip"})
        payload = request.sent
        row = payload["rows"][0]
        self.assertEqual(row["source"], "datapack")
        self.assertEqual(row["decision"], "no-base")
        self.assertEqual(row["kind"], "그림체")
        self.assertIn("그림체A", row["label"])

    def test_backup_apply_round_trip_returns_undo_handle(self):
        self.call("/api/merge_preview", b"BLOB", {"X-Source": "backup"})
        self.application.backup_preview_sha256 = "bk-sha"
        body = json.dumps({
            "source": "backup",
            "sha256": "bk-sha",
            "diff_fingerprint": "bk-diff",
            "selected": ["chg-1"],
        }).encode("utf-8")
        request = self.call("/api/merge_apply", body)
        payload = request.sent
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["undo"], {"source": "backup", "id": "B-1"})
        self.assertEqual(self.restore_log[0][1], "bk-sha")
        self.assertEqual(self.restore_log[0][2], ["chg-1"])
        undo = self.call(
            "/api/merge_undo",
            json.dumps({"source": "backup", "id": "B-1"}).encode("utf-8"))
        self.assertTrue(undo.sent["ok"])

    def test_datapack_apply_round_trip_returns_undo_handle(self):
        self.call(
            "/api/merge_preview", b"PACK",
            {"X-Source": "datapack", "X-Filename": "팩.zip"})
        self.application.pack_preview_sha256 = "pk-sha"
        body = json.dumps({
            "source": "datapack",
            "sha256": "pk-sha",
            "diff_fingerprint": "pk-diff",
            "selected": ["pk-1"],
        }).encode("utf-8")
        request = self.call("/api/merge_apply", body)
        payload = request.sent
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["undo"], {"source": "datapack", "id": "PB-1"})
        blob, filename, kwargs = self.import_log[0]
        self.assertEqual(blob, b"PACK")
        self.assertEqual(kwargs["selected_conflicts"], ["pk-1"])
        undo = self.call(
            "/api/merge_undo",
            json.dumps({"source": "datapack", "id": "PB-1"}).encode("utf-8"))
        self.assertTrue(undo.sent["ok"])

    def test_unknown_source_is_rejected(self):
        request = self.call(
            "/api/merge_preview", b"x", {"X-Source": "ftp"})
        self.assertFalse(request.sent["ok"])
        request = self.call(
            "/api/merge_apply",
            json.dumps({"source": "x"}).encode("utf-8"))
        self.assertFalse(request.sent["ok"])


if __name__ == "__main__":
    unittest.main()
