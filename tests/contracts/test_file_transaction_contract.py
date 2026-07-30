# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.nai_studio.runtime.data_files import (  # noqa: E402
    _atomic_write_bytes,
    atomic_write_json,
    load_json_recover,
    shared_data_transaction,
)
from src.nai_studio.runtime.file_transaction import (  # noqa: E402
    FileTransactionError,
    FileTransactionOperations,
    FileTransactionPaths,
    begin_file_transaction,
    commit_file_transaction,
    recover_file_transactions,
    rollback_file_transaction,
    stage_file_bytes,
    undo_file_transaction,
)


class _CrashingReplace:
    """N번째 os.replace에서 중단을 주입해 재기동 시나리오를 만든다."""

    def __init__(self, fail_at: int):
        self.fail_at = fail_at
        self.calls = 0

    def __call__(self, source, target):
        self.calls += 1
        if self.calls == self.fail_at:
            raise OSError("주입한 중단 지점")
        os.replace(source, target)


def make_operations(replace=os.replace) -> FileTransactionOperations:
    return FileTransactionOperations(
        transaction=shared_data_transaction,
        atomic_write_bytes=_atomic_write_bytes,
        atomic_write_json=atomic_write_json,
        load_json=load_json_recover,
        replace=replace,
        info=lambda *_: None,
        warning=lambda *_: None,
    )


class FileTransactionContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nais-file-txn-")
        self.root = Path(self.temp.name)
        self.paths = FileTransactionPaths(root=self.root)
        self.operations = make_operations()
        (self.root / "수집").mkdir()
        (self.root / "수집" / "그림체.json").write_text(
            json.dumps({"rows": ["기존"]}), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def stage_two(self, operations=None):
        operations = operations or self.operations
        journal = begin_file_transaction(self.paths, operations, "시험 반영")
        stage_file_bytes(
            self.paths, operations, journal,
            "수집/그림체.json", json.dumps({"rows": ["새"]}).encode("utf-8"))
        stage_file_bytes(
            self.paths, operations, journal,
            "후보사전.json", b'{"new": true}')
        return journal

    def test_commit_applies_all_files_and_records_hashes(self):
        journal = self.stage_two()
        result = commit_file_transaction(self.paths, self.operations, journal)
        self.assertTrue(result["ok"])
        self.assertEqual(
            json.loads((self.root / "수집" / "그림체.json").read_text("utf-8")),
            {"rows": ["새"]})
        self.assertTrue((self.root / "후보사전.json").exists())
        saved = load_json_recover(
            self.paths.journal_root / journal["id"] / "journal.json")
        self.assertEqual(saved["status"], "committed")
        first = saved["entries"][0]
        self.assertEqual(len(first["new_sha256"]), 64)
        self.assertEqual(len(first["prior_sha256"]), 64)
        self.assertFalse(first["prior_missing"])
        self.assertTrue(saved["entries"][1]["prior_missing"])

    def test_target_path_escape_is_rejected(self):
        journal = begin_file_transaction(self.paths, self.operations, "탈출")
        for bad in ("../밖.json", "C:/절대.json", "/절대.json"):
            with self.assertRaises(FileTransactionError):
                stage_file_bytes(
                    self.paths, self.operations, journal, bad, b"{}")

    def test_crash_then_restart_resumes_to_full_apply(self):
        crashing = make_operations(replace=_CrashingReplace(fail_at=2))
        journal = self.stage_two(crashing)
        with self.assertRaises(OSError):
            commit_file_transaction(self.paths, crashing, journal)
        # 첫 파일만 반영된 채 중단됨
        self.assertEqual(
            json.loads((self.root / "수집" / "그림체.json").read_text("utf-8")),
            {"rows": ["새"]})
        self.assertFalse((self.root / "후보사전.json").exists())
        notices = recover_file_transactions(self.paths, self.operations)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]["action"], "resumed")
        self.assertTrue((self.root / "후보사전.json").exists())
        saved = load_json_recover(
            self.paths.journal_root / journal["id"] / "journal.json")
        self.assertEqual(saved["status"], "committed")

    def test_crash_with_corrupt_staging_rolls_back_everything(self):
        crashing = make_operations(replace=_CrashingReplace(fail_at=2))
        journal = self.stage_two(crashing)
        with self.assertRaises(OSError):
            commit_file_transaction(self.paths, crashing, journal)
        staged = (
            self.paths.journal_root / journal["id"]
            / "staging" / "후보사전.json")
        staged.write_bytes(b"corrupted")
        notices = recover_file_transactions(self.paths, self.operations)
        self.assertEqual(notices[0]["action"], "rolled-back")
        self.assertEqual(
            json.loads((self.root / "수집" / "그림체.json").read_text("utf-8")),
            {"rows": ["기존"]})
        self.assertFalse((self.root / "후보사전.json").exists())
        self.assertEqual(notices[0]["conflicts"], [])

    def test_undo_restores_prior_bytes_and_removes_created_files(self):
        journal = self.stage_two()
        commit_file_transaction(self.paths, self.operations, journal)
        result = undo_file_transaction(
            self.paths, self.operations, journal["id"])
        self.assertTrue(result["ok"])
        self.assertEqual(
            json.loads((self.root / "수집" / "그림체.json").read_text("utf-8")),
            {"rows": ["기존"]})
        self.assertFalse((self.root / "후보사전.json").exists())
        saved = load_json_recover(
            self.paths.journal_root / journal["id"] / "journal.json")
        self.assertEqual(saved["status"], "undone")
        # 새로 만들었던 파일도 지우지 않고 보관된다
        kept = (
            self.paths.journal_root / journal["id"]
            / "backup" / "새파일보관" / "후보사전.json")
        self.assertTrue(kept.exists())

    def test_user_modified_file_is_preserved_as_conflict_on_undo(self):
        journal = self.stage_two()
        commit_file_transaction(self.paths, self.operations, journal)
        target = self.root / "수집" / "그림체.json"
        target.write_text(json.dumps({"rows": ["사용자 수정"]}), "utf-8")
        result = undo_file_transaction(
            self.paths, self.operations, journal["id"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["conflicts"], ["수집/그림체.json"])
        self.assertEqual(
            json.loads(target.read_text("utf-8")), {"rows": ["사용자 수정"]})
        # 충돌 안 난 항목은 되돌아간다
        self.assertFalse((self.root / "후보사전.json").exists())

    def test_staging_only_journal_is_abandoned_without_touching_data(self):
        begin_file_transaction(self.paths, self.operations, "준비만")
        notices = recover_file_transactions(self.paths, self.operations)
        self.assertEqual(notices, [])
        journals = list(self.paths.journal_root.glob("*/journal.json"))
        self.assertEqual(len(journals), 1)
        self.assertEqual(
            load_json_recover(journals[0])["status"], "abandoned")

    def test_interrupted_rollback_resumes_rollback_not_apply(self):
        crashing = make_operations(replace=_CrashingReplace(fail_at=2))
        journal = self.stage_two(crashing)
        with self.assertRaises(OSError):
            commit_file_transaction(self.paths, crashing, journal)
        # 되돌리기 방향만 journal에 남기고 재기동을 흉내낸다
        journal_path = (
            self.paths.journal_root / journal["id"] / "journal.json")
        saved = load_json_recover(journal_path)
        saved["status"] = "rolling-back"
        atomic_write_json(journal_path, saved, keep_backup=False)
        notices = recover_file_transactions(self.paths, self.operations)
        self.assertEqual(notices[0]["action"], "rolled-back")
        self.assertEqual(
            json.loads((self.root / "수집" / "그림체.json").read_text("utf-8")),
            {"rows": ["기존"]})

    def test_journal_never_stores_absolute_paths_or_tokens(self):
        journal = self.stage_two()
        commit_file_transaction(self.paths, self.operations, journal)
        raw = (
            self.paths.journal_root / journal["id"] / "journal.json"
        ).read_text("utf-8")
        self.assertNotIn(str(self.root).replace("\\", "\\\\"), raw)
        self.assertNotIn("pst-", raw)

    def test_second_recovery_run_is_a_no_op(self):
        journal = self.stage_two()
        commit_file_transaction(self.paths, self.operations, journal)
        self.assertEqual(
            recover_file_transactions(self.paths, self.operations), [])
        self.assertEqual(
            recover_file_transactions(self.paths, self.operations), [])

    def test_explicit_rollback_of_unfinished_transaction(self):
        crashing = make_operations(replace=_CrashingReplace(fail_at=2))
        journal = self.stage_two(crashing)
        with self.assertRaises(OSError):
            commit_file_transaction(self.paths, crashing, journal)
        result = rollback_file_transaction(
            self.paths, self.operations, journal)
        self.assertTrue(result["ok"])
        self.assertEqual(
            json.loads((self.root / "수집" / "그림체.json").read_text("utf-8")),
            {"rows": ["기존"]})


if __name__ == "__main__":
    unittest.main()
