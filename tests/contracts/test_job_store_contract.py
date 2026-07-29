# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.nai_studio.runtime.jobs import (  # noqa: E402
    acquire_lease,
    new_job,
    transition_job,
    update_progress,
)
from src.nai_studio.runtime.store import (  # noqa: E402
    INDEX_SCHEMA,
    JobNotFoundError,
    JobStore,
    JobStoreCorruptionError,
    JobStoreError,
)


BLUEPRINT = {
    "style": {"name": "store contract"},
    "generation": {"width": 512, "height": 512, "seed": 1},
}
PAYLOAD = {"input": "not persisted", "parameters": {"seed": 1}}


def make_job(job_id="job-one", request_id="req-one", total=1):
    return new_job(
        "single",
        blueprint=BLUEPRINT,
        payload=PAYLOAD,
        job_id=job_id,
        request_id=request_id,
        total=total,
        now="2026-07-29T00:00:00Z",
    )


class JobStoreContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nais-job-store-")
        self.root = Path(self.temp.name)
        self.store = JobStore(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_save_get_list_and_restart_keep_valid_snapshots(self):
        first = make_job()
        second = make_job("job-two", "req-two")
        self.store.save(first)
        self.store.save(second)

        restarted = JobStore(self.root)
        self.assertEqual(restarted.get("job-one"), first)
        self.assertEqual(
            [job["id"] for job in restarted.list()], ["job-one", "job-two"])
        index = json.loads(
            (self.root / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index, {
            "schema": INDEX_SCHEMA,
            "job_ids": ["job-one", "job-two"],
        })
        self.assertTrue((self.root / "job-one.json").is_file())
        self.assertTrue((self.root / "job-two.json").is_file())

    def test_path_traversal_and_raw_secret_fields_are_rejected(self):
        with self.assertRaises(JobStoreError):
            self.store.get("../outside")
        with self.assertRaises(JobStoreError):
            self.store.get("C:\\outside")

        job = make_job()
        job["metadata"]["token"] = "pst-ne-must-not-persist"
        with self.assertRaises(JobStoreError):
            self.store.save(job)
        self.assertFalse((self.root / "job-one.json").exists())

        job = make_job()
        job["payload"] = {"input": "raw"}
        with self.assertRaises(JobStoreError):
            self.store.save(job)

    def test_failure_during_final_replace_keeps_previous_snapshot(self):
        first = make_job()
        self.store.save(first)
        changed = update_progress(
            first, completed=1, message="new state",
            now="2026-07-29T00:01:00Z")

        from src.nai_studio.runtime import store as store_module
        real_replace = store_module.os.replace
        calls = {"count": 0}

        def fail_main_replace(source, destination):
            calls["count"] += 1
            # 기존 Job의 .bak 교체는 성공시키고, 새 주 파일 교체에서 실패시킨다.
            if calls["count"] == 2:
                raise OSError("injected replace failure")
            return real_replace(source, destination)

        with patch.object(store_module.os, "replace", side_effect=fail_main_replace):
            with self.assertRaises(OSError):
                self.store.save(changed)

        self.assertEqual(self.store.get("job-one"), first)
        self.assertEqual(
            list(self.root.glob(".job-one.json.*.tmp")), [])

    def test_corrupt_primary_is_restored_only_from_valid_backup(self):
        first = make_job()
        self.store.save(first)
        second = update_progress(
            first, completed=1, now="2026-07-29T00:01:00Z")
        self.store.save(second)

        primary = self.root / "job-one.json"
        backup = self.root / "job-one.json.bak"
        self.assertTrue(backup.is_file())
        primary.write_bytes(b'{"cut":')

        restored = self.store.get("job-one")
        self.assertEqual(restored, first)
        self.assertEqual(
            json.loads(primary.read_text(encoding="utf-8"))["progress"],
            first["progress"],
        )

    def test_two_corrupt_copies_raise_and_preserve_original_bytes(self):
        first = make_job()
        self.store.save(first)
        self.store.save(update_progress(first, completed=1))
        primary = self.root / "job-one.json"
        backup = self.root / "job-one.json.bak"
        primary.write_bytes(b"broken-primary")
        backup.write_bytes(b"broken-backup")
        before_primary = primary.read_bytes()
        before_backup = backup.read_bytes()

        with self.assertRaises(JobStoreCorruptionError):
            self.store.get("job-one")
        self.assertEqual(primary.read_bytes(), before_primary)
        self.assertEqual(backup.read_bytes(), before_backup)

        with self.assertRaises(JobStoreCorruptionError):
            self.store.save(make_job())
        self.assertEqual(primary.read_bytes(), before_primary)
        self.assertEqual(backup.read_bytes(), before_backup)

    def test_recover_all_pauses_inflight_job_and_clears_lease(self):
        job = transition_job(make_job(), "preparing")
        job = acquire_lease(job, "worker", lease_id="lease-one")
        job = transition_job(job, "sending")
        self.store.save(job)

        restarted = JobStore(self.root)
        recovered = restarted.recover_all()
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["phase"], "paused")
        self.assertIsNone(recovered[0]["resource"]["lease"])
        self.assertEqual(
            restarted.get("job-one")["error"]["code"], "runtime-interrupted")

    def test_reconcile_saves_observed_results_cost_and_completion(self):
        job = transition_job(make_job(), "preparing")
        job = transition_job(job, "sending")
        self.store.save(job)
        changed = self.store.reconcile("job-one", {
            "results": [{
                "id": "result-one",
                "artifact": "output/one.webp",
                "content_hash": "a" * 64,
            }],
            "progress": {"completed": 1, "failed": 0, "total": 1},
            "actual_cost": 5,
            "artifacts_intact": True,
            "confirmed_complete": True,
        })
        self.assertEqual(changed["phase"], "completed")
        self.assertEqual(changed["cost"]["actual"], 5)
        self.assertEqual(changed["lineage"]["result_ids"], ["result-one"])
        self.assertEqual(JobStore(self.root).get("job-one"), changed)

    def test_index_omission_is_reconciled_without_losing_job_file(self):
        self.store.save(make_job())
        index_path = self.root / "index.json"
        index_path.write_text(
            json.dumps({"schema": INDEX_SCHEMA, "job_ids": []}),
            encoding="utf-8",
        )
        restarted = JobStore(self.root)
        self.assertEqual([job["id"] for job in restarted.list()], ["job-one"])
        fixed = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(fixed["job_ids"], ["job-one"])

    def test_two_corrupt_index_copies_block_save_before_job_changes(self):
        first = make_job()
        self.store.save(first)
        self.store.save(update_progress(first, completed=1))
        job_path = self.root / "job-one.json"
        before_job = job_path.read_bytes()
        index_path = self.root / "index.json"
        index_backup = self.root / "index.json.bak"
        index_path.write_bytes(b"broken-index")
        index_backup.write_bytes(b"broken-index-backup")

        with self.assertRaises(JobStoreCorruptionError):
            self.store.save(update_progress(first, message="must not land"))
        self.assertEqual(job_path.read_bytes(), before_job)

    def test_missing_job_is_distinct_from_corruption(self):
        with self.assertRaises(JobNotFoundError):
            self.store.get("job-missing")

    def test_save_does_not_modify_caller(self):
        job = make_job()
        before = copy.deepcopy(job)
        self.store.save(job)
        self.assertEqual(job, before)


if __name__ == "__main__":
    unittest.main()
