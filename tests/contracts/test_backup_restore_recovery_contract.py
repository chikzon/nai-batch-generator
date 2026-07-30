# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.nai_studio.runtime.data_files import (  # noqa: E402
    _atomic_write_bytes,
    atomic_write_json,
    load_settings_recover,
    recoverable_remove,
    shared_data_transaction,
)
from src.nai_studio.services.user_backup_store import (  # noqa: E402
    UserBackupOperations,
    UserBackupPaths,
    UserBackupSourcePaths,
    recover_unfinished_restores,
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class BackupRestoreRecoveryContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nais-restore-rec-")
        self.base = Path(self.temp.name)
        sources = UserBackupSourcePaths(
            settings_file=self.base / "설정.json",
            builder_file=self.base / "후보사전.json",
            spec_file=self.base / "규격.json",
            options_file=self.base / "옵션.json",
            tag_dir=self.base / "태그",
            settings_dir=self.base / "세팅",
            schema_dir=self.base / "씬규격",
            sceneset_dir=self.base / "씬프리셋",
            style_dir=self.base / "그림체",
            character_dir=self.base / "캐릭터",
            fragment_dir=self.base / "조각",
            vibe_dir=self.base / "수집" / "바이브",
            picks_file=self.base / "선별.json",
            scenes_file=self.base / "씬.json",
        )
        self.paths = UserBackupPaths(
            base_dir=self.base,
            profile_dir=self.base,
            sources=sources,
        )
        self.operations = UserBackupOperations(
            transaction=shared_data_transaction,
            atomic_write_bytes=_atomic_write_bytes,
            atomic_write_json=atomic_write_json,
            load_settings=load_settings_recover,
            rollback=lambda *_: None,
            after_restore=lambda: None,
            now=datetime.now,
            random_bytes=os.urandom,
            warning=lambda *_: None,
            recoverable_remove=recoverable_remove,
        )
        self.journal_root = self.base / "복원기록"

    def tearDown(self):
        self.temp.cleanup()

    def crashed_restore(self, status="applying", tamper_after=False):
        """복원이 두 파일을 적용한 직후 중단된 상태를 만든다."""
        original = json.dumps({"단계": ["원본"]}).encode("utf-8")
        applied = json.dumps({"단계": ["복원값"]}).encode("utf-8")
        created = json.dumps({"새": True}).encode("utf-8")
        (self.base / "후보사전.json").write_bytes(applied)
        (self.base / "규격.json").write_bytes(created)
        batch = "20260730-120000-abc123"
        journal = self.journal_root / batch
        _atomic_write_bytes(
            journal / "before" / "common" / "후보사전.json",
            original, keep_backup=False)
        record = {
            "schema": "nais-restore-journal/v1",
            "id": batch,
            "backup_sha256": "0" * 64,
            "status": status,
            "operations": [
                {
                    "path": "common/후보사전.json",
                    "new": False,
                    "applied_sha256": _sha(applied),
                },
                {
                    "path": "common/규격.json",
                    "new": True,
                    "applied_sha256": _sha(created),
                },
            ],
            "completed": [
                "common/후보사전.json",
                "common/규격.json",
            ],
        }
        if tamper_after:
            (self.base / "후보사전.json").write_bytes(b'{"user": "edit"}')
        atomic_write_json(
            journal / "journal.json", record, indent=1, keep_backup=False)
        return batch, original

    def test_applying_journal_is_rolled_back_on_startup(self):
        batch, original = self.crashed_restore()
        notices = recover_unfinished_restores(self.paths, self.operations)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]["kind"], "backup-restore")
        self.assertEqual(notices[0]["action"], "rolled-back")
        self.assertEqual((self.base / "후보사전.json").read_bytes(), original)
        self.assertFalse((self.base / "규격.json").exists())
        record = load_settings_recover(
            self.journal_root / batch / "journal.json")
        self.assertEqual(record["status"], "rolled_back")
        self.assertTrue(record["startup_recovery"])

    def test_user_modified_file_after_crash_is_preserved(self):
        batch, original = self.crashed_restore(tamper_after=True)
        notices = recover_unfinished_restores(self.paths, self.operations)
        self.assertEqual(notices[0]["skipped"], 1)
        self.assertEqual(
            json.loads((self.base / "후보사전.json").read_text("utf-8")),
            {"user": "edit"})
        self.assertFalse((self.base / "규격.json").exists())

    def test_finished_journals_are_left_alone(self):
        batch, original = self.crashed_restore(status="complete")
        self.assertEqual(
            recover_unfinished_restores(self.paths, self.operations), [])
        record = load_settings_recover(
            self.journal_root / batch / "journal.json")
        self.assertEqual(record["status"], "complete")
        # 적용된 파일도 그대로다
        self.assertEqual(
            json.loads((self.base / "후보사전.json").read_text("utf-8")),
            {"단계": ["복원값"]})

    def test_ready_journal_with_nothing_completed_converges_quietly(self):
        batch, original = self.crashed_restore(status="ready")
        journal_file = self.journal_root / batch / "journal.json"
        record = load_settings_recover(journal_file)
        record["completed"] = []
        atomic_write_json(journal_file, record, indent=1, keep_backup=False)
        notices = recover_unfinished_restores(self.paths, self.operations)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]["files"], [])
        # 아무것도 적용 전이었으므로 파일은 손대지 않는다
        self.assertEqual(
            json.loads((self.base / "후보사전.json").read_text("utf-8")),
            {"단계": ["복원값"]})
        self.assertEqual(
            load_settings_recover(journal_file)["status"], "rolled_back")

    def test_second_run_is_a_no_op(self):
        self.crashed_restore()
        recover_unfinished_restores(self.paths, self.operations)
        self.assertEqual(
            recover_unfinished_restores(self.paths, self.operations), [])


if __name__ == "__main__":
    unittest.main()
