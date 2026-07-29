# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.nai_studio.services.job_bridge import (  # noqa: E402
    COMMAND_SCHEMA,
    JobBridgeError,
    make_job_command,
    project_comparison_progress,
    project_live_state,
    project_settings_batch_state,
)


BLUEPRINT = {
    "style": {"base": "private prompt"},
    "generation": {"width": 512, "height": 512, "seed": 1},
}
IDENTITY = {
    "prompt": "private prompt",
    "negative_prompt": "private negative",
    "token": "pst-ne-secret",
    "width": 512,
    "height": 512,
}


class JobBridgeContractTests(unittest.TestCase):
    def test_live_state_projects_progress_identity_and_exclusive_resource(self):
        live = {
            "operation": "단독 생성",
            "phase": "running",
            "running": True,
            "total": 3,
            "completed": 1,
            "failed": 0,
            "retry_count": 1,
            "retry_mode": "preview",
            "started_at": 100.5,
            "seed_key": "01",
        }
        job = project_live_state(
            live,
            kind="single",
            blueprint=BLUEPRINT,
            payload_identity=IDENTITY,
            source_job_ids=("job-parent",),
            source_result_ids=("result-source",),
        )
        self.assertEqual(job["phase"], "preparing")
        self.assertEqual(job["progress"]["completed"], 1)
        self.assertEqual(job["progress"]["total"], 3)
        self.assertEqual(job["retry"]["count"], 1)
        self.assertEqual(job["resource"], {
            "key": "novelai-generation-api",
            "mode": "exclusive",
            "lease": None,
        })
        self.assertEqual(job["lineage"]["source_job_ids"], ["job-parent"])
        self.assertEqual(job["lineage"]["source_result_ids"], ["result-source"])
        encoded = json.dumps(job, ensure_ascii=False)
        self.assertNotIn("private prompt", encoded)
        self.assertNotIn("private negative", encoded)
        self.assertNotIn("pst-ne-secret", encoded)

    def test_comparison_manifest_has_stable_id_plan_lineage_and_results(self):
        progress = {
            "signature": "a" * 64,
            "status": "running",
            "created_at": "2026-07-29 00:00:00",
            "updated_at": "2026-07-29 00:01:00",
            "folder": "비교생성/run-1",
            "mode": "both",
            "plan": {
                "count": 2,
                "private_prompt": "must hash only",
            },
            "completed": {
                "cell-1": {"file": "비교생성/run-1/one.webp"},
            },
            "errors": {},
        }
        before = copy.deepcopy(progress)
        first = project_comparison_progress(
            progress,
            source_job_ids=("job-plan",),
            source_result_ids=("result-evidence",),
        )
        second = project_comparison_progress(progress)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["request_id"], second["request_id"])
        self.assertEqual(first["phase"], "paused")
        self.assertEqual(first["lineage"]["result_ids"], ["cell-1"])
        self.assertEqual(first["metadata"]["plan"]["fingerprint"], "a" * 64)
        self.assertEqual(first["lineage"]["source_job_ids"], ["job-plan"])
        self.assertEqual(progress, before)
        self.assertNotIn(
            "must hash only", json.dumps(first, ensure_ascii=False))

    def test_settings_batch_projects_saved_results_without_claiming_completion(self):
        state = {
            "seeds": {"01": 1234},
            "progress": {
                "01": {
                    "alice": [{
                        "scene": 1,
                        "copy": 1,
                        "path": "nsfw_seed/seed_01/alice/001.webp",
                        "bytes": 123,
                        "fingerprint": "b" * 64,
                    }],
                    "bob": [{
                        "scene": 2,
                        "copy": 1,
                        "path": "nsfw_seed/seed_01/bob/002.webp",
                        "bytes": 456,
                        "fingerprint": "c" * 64,
                    }],
                },
            },
            "frag_seq": {"표정": 3},
        }
        job = project_settings_batch_state(
            state,
            seed_key="01",
            expected_total=3,
            blueprint=BLUEPRINT,
            payload_identity=IDENTITY,
            source_result_ids=("evidence-1",),
        )
        self.assertEqual(job["kind"], "setting")
        self.assertEqual(job["phase"], "paused")
        self.assertEqual(job["progress"], {
            "completed": 2,
            "failed": 0,
            "total": 3,
            "ratio": 2 / 3,
            "message": "",
        })
        self.assertEqual(len(job["results"]), 2)
        self.assertTrue(all(
            item["source_result_ids"] == ["evidence-1"]
            for item in job["results"]
        ))
        self.assertEqual(job["metadata"]["seed_key"], "01")
        encoded = json.dumps(job, ensure_ascii=False)
        self.assertNotIn("private prompt", encoded)
        self.assertNotIn("pst-ne-secret", encoded)

    def test_completed_settings_requires_evidence_from_live_or_expected_total(self):
        state = {
            "seeds": {"01": 1},
            "progress": {"01": {"char": [
                {"scene": 1, "copy": 1, "path": "one.webp",
                 "fingerprint": "d" * 64},
            ]}},
        }
        inferred = project_settings_batch_state(state, seed_key="01")
        self.assertEqual(inferred["phase"], "paused")
        exact = project_settings_batch_state(
            state, seed_key="01", expected_total=1)
        self.assertEqual(exact["phase"], "completed")
        live = project_settings_batch_state(
            state, seed_key="01", expected_total=2,
            live={"phase": "completed"})
        self.assertEqual(live["phase"], "completed")

    def test_pause_cancel_retry_and_resume_commands_are_safe(self):
        active = project_live_state(
            {"phase": "running", "operation": "생성", "total": 1},
            kind="single",
            blueprint=BLUEPRINT,
            payload_identity=IDENTITY,
        )
        pause = make_job_command(active, "pause")
        self.assertEqual(pause["schema"], COMMAND_SCHEMA)
        self.assertEqual(pause["next_phase"], "paused")
        self.assertEqual(pause["handler"], {
            "target": "live_state", "operation": "request_stop"})

        paused_job = project_live_state(
            {"phase": "stopped", "operation": "생성", "can_retry": True},
            kind="single",
            blueprint=BLUEPRINT,
            payload_identity=IDENTITY,
        )
        resume = make_job_command(paused_job, "resume")
        cancel = make_job_command(paused_job, "cancel")
        self.assertEqual(resume["next_phase"], "queued")
        self.assertTrue(resume["resource"]["requires_idle"])
        self.assertEqual(cancel["next_phase"], "cancelled")

        failed = project_live_state(
            {"phase": "failed", "operation": "생성", "can_retry": True},
            kind="single",
            blueprint=BLUEPRINT,
            payload_identity=IDENTITY,
        )
        retry = make_job_command(failed, "retry")
        self.assertEqual(retry["next_phase"], "queued")
        self.assertEqual(retry["update"]["retry_count"], 1)

        encoded = json.dumps(
            {"pause": pause, "resume": resume, "retry": retry},
            ensure_ascii=False,
        )
        self.assertNotIn("private prompt", encoded)
        self.assertNotIn("pst-ne-secret", encoded)

    def test_kind_specific_resume_commands_point_to_existing_legacy_flow(self):
        comparison = project_comparison_progress({
            "signature": "e" * 64,
            "status": "stopped",
            "folder": "비교생성/run",
            "plan": {"count": 1},
            "completed": {},
            "errors": {},
        })
        command = make_job_command(comparison, "resume")
        self.assertEqual(command["handler"], {
            "target": "comparison",
            "operation": "resume",
            "folder": "비교생성/run",
        })

        setting = project_settings_batch_state(
            {"seeds": {"03": 3}, "progress": {"03": {}}},
            seed_key="03",
            live={"phase": "stopped"},
        )
        command = make_job_command(setting, "resume")
        self.assertEqual(command["handler"], {
            "target": "generation",
            "operation": "resume",
            "seed_key": "03",
        })

    def test_reconcile_command_whitelists_observation_and_projects_completion(self):
        job = project_live_state(
            {"phase": "running", "operation": "생성", "total": 1},
            kind="single",
            blueprint=BLUEPRINT,
            payload_identity=IDENTITY,
        )
        command = make_job_command(job, "reconcile", observation={
            "results": [{
                "id": "result-1",
                "artifact": "output/one.webp",
                "content_hash": "f" * 64,
                "prompt": "must disappear",
            }],
            "progress": {
                "completed": 1, "failed": 0, "total": 1,
                "message": "private message",
            },
            "actual_cost": 4,
            "artifacts_intact": True,
            "confirmed_complete": True,
            "token": "pst-ne-secret",
        })
        self.assertEqual(command["next_phase"], "completed")
        self.assertEqual(command["update"]["actual_cost"], 4)
        self.assertEqual(command["update"]["result_ids"], ["result-1"])
        encoded = json.dumps(command, ensure_ascii=False)
        self.assertNotIn("must disappear", encoded)
        self.assertNotIn("private message", encoded)
        self.assertNotIn("pst-ne-secret", encoded)

    def test_invalid_commands_and_inputs_do_not_mutate_sources(self):
        live = {"phase": "stopped", "operation": "생성"}
        before = copy.deepcopy(live)
        job = project_live_state(live, kind="single")
        with self.assertRaises(JobBridgeError):
            make_job_command(job, "pause")
        with self.assertRaises(JobBridgeError):
            make_job_command(job, "unknown")
        self.assertEqual(live, before)


if __name__ == "__main__":
    unittest.main()
