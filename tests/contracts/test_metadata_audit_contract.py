# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import hashlib
import json
import unittest

from src.nai_studio.services.metadata_audit import (
    MAX_AUDIT_CHUNK,
    metadata_audit_bundle,
    metadata_audit_failures,
    metadata_audit_restoration_queue,
    metadata_audit_summary,
    new_metadata_audit,
    pause_metadata_audit,
    resume_metadata_audit,
    retry_metadata_failures,
    run_metadata_audit_chunk,
)


TOKEN = "pst-ne-secret-that-must-not-enter-the-ledger"
PROMPT = "1.25::raw prompt::, secret character negative"
ABSOLUTE_PATH = r"C:\Users\private\owned\source.png"


def indexed(path, payload):
    return {
        "path": path,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


class MetadataAuditContractTests(unittest.TestCase):
    def assert_ledger_safe(self, value):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn(PROMPT, text)
        self.assertNotIn(ABSOLUTE_PATH, text)
        self.assertNotIn("89504e470d0a", text)
        return text

    def test_audits_at_most_500_entries_then_resumes(self):
        payloads = {
            f"owned/{index:03d}.png": f"png-{index}".encode()
            for index in range(MAX_AUDIT_CHUNK + 1)
        }
        entries = [indexed(path, payload) for path, payload in payloads.items()]
        reads = []

        def reader(entry):
            reads.append(entry["path"])
            return payloads[entry["path"]]

        state = new_metadata_audit(entries, chunk_size=900)
        first = run_metadata_audit_chunk(
            state,
            reader=reader,
            metadata_inspector=lambda payload, kind, path: {"found": True},
        )
        self.assertEqual(state["cursor"], 0)
        self.assertEqual(first["chunk_size"], 500)
        self.assertEqual(first["cursor"], 500)
        self.assertEqual(first["status"], "paused")
        self.assertEqual(len(reads), 500)

        final = resume_metadata_audit(
            first,
            reader=reader,
            metadata_inspector=lambda payload, kind, path: {"found": True},
        )
        self.assertEqual(final["cursor"], 501)
        self.assertEqual(final["status"], "completed")
        self.assertEqual(len(reads), 501)
        self.assertEqual(
            metadata_audit_summary(final)["status_counts"]["found"],
            501,
        )

    def test_classifies_png_webp_json_and_unsupported_without_writes(self):
        payloads = {
            "owned/a.PNG": b"png-a",
            "owned/b.webp": b"webp-b",
            "owned/c.json": b'{"Comment": {}}',
            "owned/readme.txt": b"not inspected",
        }
        entries = [indexed(path, payload) for path, payload in payloads.items()]
        original_entries = copy.deepcopy(entries)
        original_payloads = copy.deepcopy(payloads)
        inspected = []

        def reader(entry):
            return payloads[entry["path"]]

        def inspector(payload, kind, path):
            inspected.append((kind, path))
            if kind == "webp":
                return None
            if kind == "json":
                raise ValueError(f"{PROMPT} at {ABSOLUTE_PATH}")
            return {"metadata_status": "ok"}

        final = run_metadata_audit_chunk(
            new_metadata_audit(entries),
            reader=reader,
            metadata_inspector=inspector,
        )
        self.assertEqual(entries, original_entries)
        self.assertEqual(payloads, original_payloads)
        self.assertEqual(
            [(item["kind"], item["status"]) for item in final["items"]],
            [
                ("png", "found"),
                ("webp", "none"),
                ("json", "error"),
                ("unsupported", "none"),
            ],
        )
        self.assertEqual(
            inspected,
            [
                ("png", "owned/a.PNG"),
                ("webp", "owned/b.webp"),
                ("json", "owned/c.json"),
            ],
        )
        self.assertEqual(
            final["items"][2]["error_code"],
            "inspect-ValueError",
        )
        self.assert_ledger_safe(final)

    def test_discards_bytes_metadata_prompts_tokens_and_absolute_paths(self):
        payload = bytes.fromhex("89504e470d0a") + b"private-image-bytes"
        entry = indexed("owned/source.png", payload)

        def inspector(raw, kind, path):
            return {
                "found": True,
                "prompt": PROMPT,
                "token": TOKEN,
                "source_path": ABSOLUTE_PATH,
                "image_bytes": raw,
            }

        final = run_metadata_audit_chunk(
            new_metadata_audit([entry]),
            reader=lambda request: payload,
            metadata_inspector=inspector,
        )
        bundle = metadata_audit_bundle(final)
        self.assertEqual(final["items"][0]["status"], "found")
        self.assertEqual(
            set(final["items"][0]),
            {"path", "sha256", "kind", "status", "attempts", "error_code"},
        )
        queue = bundle["restoration_queue"]
        evidence = queue["items"][0]["result"]["evidence_candidate"]
        self.assertEqual(evidence["actual_generation"]["base"], "")
        self.assertEqual(evidence["actual_generation"]["negative"], "")
        self.assertIsNone(evidence["raw_metadata"])
        self.assertEqual(
            evidence["image"]["content_sha256"],
            entry["sha256"],
        )
        self.assertEqual(evidence["image"]["filename"], "source.png")
        self.assert_ledger_safe(bundle)

    def test_pause_does_not_read_and_resume_processes_next_chunk(self):
        payload = b"owned"
        state = pause_metadata_audit(
            new_metadata_audit([indexed("owned/a.webp", payload)])
        )
        reads = []

        def reader(entry):
            reads.append(entry["path"])
            return payload

        unchanged = run_metadata_audit_chunk(
            state,
            reader=reader,
            metadata_inspector=lambda raw, kind, path: True,
        )
        self.assertEqual(unchanged["status"], "paused")
        self.assertEqual(reads, [])

        final = resume_metadata_audit(
            unchanged,
            reader=reader,
            metadata_inspector=lambda raw, kind, path: True,
        )
        self.assertEqual(reads, ["owned/a.webp"])
        self.assertEqual(final["status"], "completed")

    def test_retries_only_selected_failures_and_keeps_cursor(self):
        payloads = {
            "owned/a.png": b"a",
            "owned/b.png": b"b",
        }
        attempts = {path: 0 for path in payloads}

        def reader(entry):
            path = entry["path"]
            attempts[path] += 1
            if attempts[path] == 1:
                raise OSError(f"{TOKEN} {ABSOLUTE_PATH}")
            return payloads[path]

        state = run_metadata_audit_chunk(
            new_metadata_audit(
                [indexed(path, payload) for path, payload in payloads.items()]
            ),
            reader=reader,
            metadata_inspector=lambda raw, kind, path: True,
        )
        self.assertEqual(state["status"], "partial")
        self.assertEqual(len(metadata_audit_failures(state)), 2)
        cursor = state["cursor"]

        one_fixed = retry_metadata_failures(
            state,
            reader=reader,
            metadata_inspector=lambda raw, kind, path: True,
            paths=["owned/a.png"],
        )
        self.assertEqual(one_fixed["cursor"], cursor)
        self.assertEqual(
            [item["status"] for item in one_fixed["items"]],
            ["found", "error"],
        )
        self.assertEqual(one_fixed["items"][0]["attempts"], 2)
        self.assertEqual(one_fixed["items"][1]["attempts"], 1)

        final = retry_metadata_failures(
            one_fixed,
            reader=reader,
            metadata_inspector=lambda raw, kind, path: True,
        )
        self.assertEqual(final["status"], "completed")
        self.assertEqual(metadata_audit_failures(final), [])
        self.assert_ledger_safe(final)

    def test_rejects_absolute_traversal_and_bad_hash_without_reading(self):
        entries = [
            {"path": ABSOLUTE_PATH, "sha256": "a" * 64},
            {"path": "../escape.png", "sha256": "b" * 64},
            {"path": "owned/no-hash.png", "sha256": PROMPT},
        ]
        reads = []
        final = run_metadata_audit_chunk(
            new_metadata_audit(entries),
            reader=lambda entry: reads.append(entry) or b"unused",
            metadata_inspector=lambda raw, kind, path: True,
        )
        self.assertEqual(reads, [])
        self.assertEqual(
            [item["error_code"] for item in final["items"]],
            [
                "invalid-relative-path",
                "invalid-relative-path",
                "invalid-sha256",
            ],
        )
        self.assertEqual(final["status"], "partial")
        self.assert_ledger_safe(final)

    def test_detects_content_change_and_projects_only_found_items(self):
        indexed_payload = b"before"
        actual_payload = b"after"
        changed = run_metadata_audit_chunk(
            new_metadata_audit([indexed("owned/changed.png", indexed_payload)]),
            reader=lambda entry: actual_payload,
            metadata_inspector=lambda raw, kind, path: True,
        )
        self.assertEqual(changed["items"][0]["status"], "error")
        self.assertEqual(changed["items"][0]["error_code"], "content-changed")
        self.assertEqual(metadata_audit_restoration_queue(changed)["items"], [])
        self.assert_ledger_safe(changed)


if __name__ == "__main__":
    unittest.main()
