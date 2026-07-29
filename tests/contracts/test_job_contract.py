# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.nai_studio.runtime.jobs import (
    JOB_KINDS,
    NAI_RESOURCE_KEY,
    JobContractError,
    acquire_lease,
    add_result,
    fingerprint_payload,
    from_comparison_progress,
    from_legacy_job_record,
    lease_expired,
    new_job,
    reconcile_job,
    recover_job,
    release_lease,
    retry_job,
    snapshot_from_json,
    snapshot_to_json,
    transition_job,
    update_cost,
    update_progress,
    validate_job,
)


BLUEPRINT = {
    "style": {"name": "검증 그림체", "base": "long prompt"},
    "characters": [{"name": "A", "prompt": "1girl"}],
    "generation": {"width": 512, "height": 512, "seed": 7},
}
PAYLOAD = {
    "input": "long prompt",
    "parameters": {"seed": 7},
}


def make_job(kind="single", **kwargs):
    return new_job(
        kind,
        blueprint=BLUEPRINT,
        payload=PAYLOAD,
        request_id=kwargs.pop("request_id", "req-test"),
        job_id=kwargs.pop("job_id", "job-test"),
        now=kwargs.pop("now", "2026-07-29T00:00:00Z"),
        **kwargs,
    )


class JobContractTests(unittest.TestCase):
    def test_every_nai_operation_uses_one_schema_and_exclusive_resource(self):
        for kind in JOB_KINDS:
            with self.subTest(kind=kind):
                job = make_job(kind, job_id=f"job-{kind}")
                self.assertEqual(job["kind"], kind)
                self.assertEqual(job["phase"], "queued")
                self.assertEqual(job["resource"]["key"], NAI_RESOURCE_KEY)
                self.assertEqual(job["resource"]["mode"], "exclusive")
                self.assertNotIn("payload", job)
                self.assertNotIn("blueprint", job)

    def test_payload_hash_is_stable_and_does_not_persist_secrets(self):
        first = {
            "parameters": {"seed": 7},
            "input": "same",
            "token": "pst-ne-secret",
            "Authorization": "Bearer secret",
        }
        second = {
            "input": "same",
            "parameters": {"seed": 7},
            "api_key": "another-secret",
            "access_token": "third-secret",
        }
        self.assertEqual(fingerprint_payload(first), fingerprint_payload(second))
        text = snapshot_to_json(new_job(
            "single", blueprint=BLUEPRINT, payload=first,
            request_id="req-secret", job_id="job-secret",
            now="2026-07-29T00:00:00Z"))
        self.assertNotIn("pst-ne-secret", text)
        self.assertNotIn("Bearer secret", text)
        self.assertNotIn("long prompt", text)

    def test_transition_graph_blocks_skips_and_atomic_save_interruption(self):
        job = make_job()
        with self.assertRaises(JobContractError):
            transition_job(job, "receiving")
        job = transition_job(job, "preparing", now="2026-07-29T00:00:01Z")
        job = transition_job(job, "sending", now="2026-07-29T00:00:02Z")
        job = transition_job(job, "receiving", now="2026-07-29T00:00:03Z")
        job = transition_job(job, "saving", now="2026-07-29T00:00:04Z")
        with self.assertRaises(JobContractError):
            transition_job(job, "cancelled")
        job = transition_job(job, "completed", now="2026-07-29T00:00:05Z")
        with self.assertRaises(JobContractError):
            transition_job(job, "queued")

    def test_retry_keeps_logical_request_id_and_enforces_policy(self):
        job = make_job(retry_policy={"max_attempts": 2})
        job = transition_job(
            job, "failed",
            error={"code": "http-500", "message": "temporary", "retryable": True})
        retried = retry_job(job, now="2026-07-29T00:01:00Z")
        self.assertEqual(retried["request_id"], "req-test")
        self.assertEqual(retried["retry"]["count"], 1)
        self.assertEqual(retried["phase"], "queued")
        retried = transition_job(
            retried, "failed",
            error={"code": "http-500", "message": "temporary", "retryable": True})
        with self.assertRaises(JobContractError):
            retry_job(retried)

        permanent = transition_job(
            make_job(), "failed",
            error={"code": "bad-request", "message": "bad", "retryable": False})
        with self.assertRaises(JobContractError):
            retry_job(permanent)

    def test_progress_cost_and_result_lineage_round_trip(self):
        job = make_job(total=2, cost_preview=12)
        job = update_progress(job, completed=1, message="첫 장 저장")
        job = update_cost(job, actual=6)
        job = add_result(
            job, "result-1", artifact="output/one.webp",
            content_hash="a" * 64, source_result_ids=("source-1",))
        restored = snapshot_from_json(snapshot_to_json(job))
        self.assertEqual(restored, job)
        self.assertEqual(restored["progress"]["ratio"], 0.5)
        self.assertEqual(restored["cost"], {
            "unit": "anlas", "preview": 12, "actual": 6})
        self.assertEqual(restored["lineage"]["result_ids"], ["result-1"])
        self.assertEqual(
            restored["results"][0]["source_result_ids"], ["source-1"])

    def test_lease_is_owned_exclusive_and_released_by_matching_id(self):
        job = transition_job(make_job(), "preparing")
        job = acquire_lease(
            job, "worker-1", lease_id="lease-1",
            acquired_at="2026-07-29T00:00:00Z",
            expires_at="2026-07-29T00:00:30Z")
        self.assertFalse(lease_expired(job, now="2026-07-29T00:00:29Z"))
        self.assertTrue(lease_expired(job, now="2026-07-29T00:00:30Z"))
        with self.assertRaises(JobContractError):
            acquire_lease(job, "worker-2")
        with self.assertRaises(JobContractError):
            release_lease(job, "other-lease")
        released = release_lease(job, "lease-1")
        self.assertIsNone(released["resource"]["lease"])

    def test_restart_recovery_pauses_uncertain_call_and_reconcile_finishes(self):
        job = transition_job(make_job(total=1), "preparing")
        job = acquire_lease(job, "worker-1", lease_id="lease-1")
        job = transition_job(job, "sending")
        paused = recover_job(job, now="2026-07-29T00:10:00Z")
        self.assertEqual(paused["phase"], "paused")
        self.assertIsNone(paused["resource"]["lease"])
        self.assertEqual(paused["error"]["code"], "runtime-interrupted")
        finished = reconcile_job(paused, {
            "results": [{"id": "result-1", "artifact": "output/one.webp"}],
            "progress": {"completed": 1, "failed": 0, "total": 1},
            "actual_cost": 5,
            "artifacts_intact": True,
            "confirmed_complete": True,
        }, now="2026-07-29T00:11:00Z")
        self.assertEqual(finished["phase"], "completed")
        self.assertEqual(finished["cost"]["actual"], 5)
        self.assertEqual(finished["lineage"]["result_ids"], ["result-1"])

    def test_reconcile_reopens_completed_job_if_artifact_is_missing(self):
        job = make_job(total=1)
        for phase in ("preparing", "sending", "receiving", "saving", "completed"):
            job = transition_job(job, phase)
        reconciled = reconcile_job(job, {"artifacts_intact": False})
        self.assertEqual(reconciled["phase"], "paused")
        self.assertEqual(reconciled["error"]["code"], "artifact-missing")

    def test_existing_ledger_and_comparison_manifest_have_safe_adapters(self):
        legacy = from_legacy_job_record({
            "id": "job-old",
            "operation": "세팅 생성",
            "kind": "settings",
            "status": "interrupted",
            "created_at": "2026-07-28T10:00:00",
            "updated_at": "2026-07-28T10:01:00",
            "completed": 2,
            "failed": 1,
            "can_resume": True,
        })
        self.assertEqual(legacy["kind"], "setting")
        self.assertEqual(legacy["phase"], "paused")
        self.assertEqual(legacy["progress"]["completed"], 2)
        self.assertEqual(legacy["metadata"]["legacy_kind"], "settings")

        comparison = from_comparison_progress({
            "version": 1,
            "signature": "b" * 64,
            "status": "running",
            "created_at": "2026-07-28 10:00:00",
            "updated_at": "2026-07-28 10:01:00",
            "folder": "비교생성/run-1",
            "mode": "both",
            "plan": {"count": 2},
            "completed": {"one": {"file": "비교생성/run-1/one.webp"}},
            "errors": {},
        })
        self.assertEqual(comparison["kind"], "comparison")
        self.assertEqual(comparison["phase"], "paused")
        self.assertEqual(comparison["lineage"]["result_ids"], ["one"])
        self.assertEqual(comparison["progress"]["total"], 2)

    def test_validation_and_updates_do_not_modify_callers(self):
        job = make_job()
        before = copy.deepcopy(job)
        validate_job(job)
        update_progress(job, completed=0, message="read only")
        self.assertEqual(job, before)


if __name__ == "__main__":
    unittest.main()
