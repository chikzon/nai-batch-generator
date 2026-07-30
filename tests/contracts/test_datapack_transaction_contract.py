# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.nai_studio.runtime.data_files import (  # noqa: E402
    _atomic_write_bytes,
    atomic_write_json,
    load_json_recover,
    recoverable_remove,
    shared_data_transaction,
)
from src.nai_studio.runtime.file_transaction import (  # noqa: E402
    FileTransactionOperations,
    FileTransactionPaths,
    recover_file_transactions,
)
from src.nai_studio.services.datapack_store import (  # noqa: E402
    DatapackOperations,
    DatapackPaths,
    import_datapack_bytes,
    load_pack_log,
    undo_datapack,
)


class _CrashingReplace:
    def __init__(self, fail_at: int):
        self.fail_at = fail_at
        self.calls = 0

    def __call__(self, source, target):
        self.calls += 1
        if self.calls == self.fail_at:
            raise OSError("주입한 중단 지점")
        os.replace(source, target)


def _row_digest(item) -> str:
    raw = json.dumps(item, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DatapackTransactionContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nais-pack-txn-")
        self.base = Path(self.temp.name)
        self.paths = DatapackPaths(
            base_dir=self.base,
            style_file=self.base / "수집" / "그림체.json",
            recipe_file=self.base / "수집" / "레시피.json",
            combo_file=self.base / "수집" / "작가조합.json",
            image_cache=self.base / "수집" / "이미지캐시",
            tag_dir=self.base / "태그",
            builder_file=self.base / "후보사전.json",
            spec_file=self.base / "규격.json",
            options_file=self.base / "옵션.json",
            settings_dir=self.base / "세팅",
            character_dir=self.base / "캐릭터",
        )
        (self.base / "수집").mkdir()
        atomic_write_json(
            self.paths.style_file,
            [{"id": "기존", "prompt": "artist:old"}],
            keep_backup=False,
        )

    def tearDown(self):
        self.temp.cleanup()

    def make_operations(self, replace=os.replace) -> DatapackOperations:
        return DatapackOperations(
            transaction=shared_data_transaction,
            atomic_write_bytes=_atomic_write_bytes,
            atomic_write_json=atomic_write_json,
            load_json=load_json_recover,
            recoverable_remove=recoverable_remove,
            row_digest=_row_digest,
            character_signature=lambda record: _row_digest(record),
            delete_character_files=lambda *_, **__: None,
            sync_character_files=lambda *_, **__: None,
            save_config=lambda *_, **__: None,
            forget_caches=lambda *_, **__: None,
            pack_queue=lambda *_, **__: {"items": []},
            summarize_queue=lambda *_: {},
            warning=lambda *_: None,
            replace=replace,
        )

    def txn_boundary(self):
        paths = FileTransactionPaths(root=self.base)
        operations = FileTransactionOperations(
            transaction=shared_data_transaction,
            atomic_write_bytes=_atomic_write_bytes,
            atomic_write_json=atomic_write_json,
            load_json=load_json_recover,
            replace=os.replace,
            info=lambda *_: None,
            warning=lambda *_: None,
        )
        return paths, operations

    def two_asset_zip(self) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "그림체.json",
                json.dumps([{"id": "새것", "prompt": "artist:new"}]),
            )
            archive.writestr("후보사전.json", json.dumps({"단계": []}))
        return buffer.getvalue()

    def test_import_commits_through_journal_and_logs_transaction_id(self):
        operations = self.make_operations()
        result = import_datapack_bytes(
            self.paths, operations, self.two_asset_zip(), "팩.zip")
        self.assertTrue(result["ok"])
        rows = load_json_recover(self.paths.style_file)
        self.assertEqual([row["id"] for row in rows], ["기존", "새것"])
        self.assertTrue(self.paths.builder_file.exists())
        log_rows = load_pack_log(self.paths, operations)
        self.assertTrue(log_rows[-1]["transaction"])
        journal = load_json_recover(
            self.base / ".nai-studio" / "transactions"
            / log_rows[-1]["transaction"] / "journal.json")
        self.assertEqual(journal["status"], "committed")
        targets = {entry["target"] for entry in journal["entries"]}
        self.assertEqual(targets, {"수집/그림체.json", "후보사전.json"})

    def test_no_user_file_changes_before_commit_replace(self):
        operations = self.make_operations(replace=_CrashingReplace(fail_at=1))
        with self.assertRaises(OSError):
            import_datapack_bytes(
                self.paths, operations, self.two_asset_zip(), "팩.zip")
        # 첫 교체 지점에서 중단 → 사용자 파일은 전부 원래 그대로
        rows = load_json_recover(self.paths.style_file)
        self.assertEqual([row["id"] for row in rows], ["기존"])
        self.assertFalse(self.paths.builder_file.exists())
        self.assertEqual(load_pack_log(self.paths, self.make_operations()), [])

    def test_crash_mid_apply_then_startup_recovery_completes_all(self):
        operations = self.make_operations(replace=_CrashingReplace(fail_at=2))
        with self.assertRaises(OSError):
            import_datapack_bytes(
                self.paths, operations, self.two_asset_zip(), "팩.zip")
        txn_paths, txn_ops = self.txn_boundary()
        notices = recover_file_transactions(txn_paths, txn_ops)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]["action"], "resumed")
        rows = load_json_recover(self.paths.style_file)
        self.assertEqual([row["id"] for row in rows], ["기존", "새것"])
        self.assertTrue(self.paths.builder_file.exists())

    def test_pack_undo_round_trip_still_works_after_staged_import(self):
        operations = self.make_operations()
        result = import_datapack_bytes(
            self.paths, operations, self.two_asset_zip(), "팩.zip")
        undo = undo_datapack(self.paths, operations, result["batch"])
        self.assertTrue(undo.get("ok"), undo)
        rows = load_json_recover(self.paths.style_file)
        self.assertEqual([row["id"] for row in rows], ["기존"])

    def test_non_pack_input_leaves_only_abandoned_journal(self):
        operations = self.make_operations()
        result = import_datapack_bytes(
            self.paths, operations, b"not a pack", "이상한.txt")
        self.assertFalse(result["ok"])
        rows = load_json_recover(self.paths.style_file)
        self.assertEqual([row["id"] for row in rows], ["기존"])
        txn_paths, txn_ops = self.txn_boundary()
        self.assertEqual(recover_file_transactions(txn_paths, txn_ops), [])
        journals = list(
            (self.base / ".nai-studio" / "transactions").glob(
                "*/journal.json"))
        self.assertEqual(
            {load_json_recover(path)["status"] for path in journals},
            {"abandoned"},
        )


if __name__ == "__main__":
    unittest.main()
