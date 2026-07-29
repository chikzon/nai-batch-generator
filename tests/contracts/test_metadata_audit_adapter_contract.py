# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import src.nai_studio.services.metadata_audit_adapter as adapter_module
from src.nai_studio.services.metadata_audit_adapter import (
    DATA_INDEX_SCHEMA,
    MetadataAuditAdapter,
    MetadataAuditAdapterError,
    MetadataAuditPathError,
)


TOKEN = "pst-ne-adapter-secret-that-must-not-be-saved"
PROMPT = "1.4::private raw prompt::, negative"
ABSOLUTE_PATH = r"C:\Users\private\outside.png"


def index_entry(path, payload, **extra):
    return {
        "path": path,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        **extra,
    }


def data_index(entries, **extra):
    return {
        "schema": DATA_INDEX_SCHEMA,
        "data_dir": ABSOLUTE_PATH,
        "entries": entries,
        **extra,
    }


class MetadataAuditAdapterContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nais-metadata-adapter-")
        self.base = Path(self.temp.name) / "data"
        self.base.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write_owned(self, relative, payload):
        path = self.base.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def assert_safe(self, value):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn(PROMPT, text)
        self.assertNotIn(ABSOLUTE_PATH, text)
        self.assertNotIn("89504e470d0a", text)
        return text

    def secret_inspector(self, payload, kind, path):
        return {
            "metadata_status": "ok",
            "prompt": PROMPT,
            "token": TOKEN,
            "absolute_path": ABSOLUTE_PATH,
            "image_bytes": payload,
        }

    def test_converts_real_data_index_to_500_item_chunks_and_resumes(self):
        entries = []
        originals = {}
        for number in range(501):
            relative = f"owned/{number:03d}.png"
            payload = f"image-{number}".encode()
            self.write_owned(relative, payload)
            originals[relative] = payload
            entries.append(index_entry(
                relative,
                payload,
                prompt=PROMPT,
                token=TOKEN,
            ))
        adapter = MetadataAuditAdapter(
            self.base,
            metadata_inspector=self.secret_inspector,
        )
        started = adapter.start(data_index(entries), chunk_size=900)
        self.assertEqual(started["audit"]["chunk_size"], 500)
        self.assertEqual(started["audit"]["cursor"], 0)

        first = adapter.run_chunk()
        self.assertEqual(first["audit"]["cursor"], 500)
        self.assertEqual(first["audit"]["status"], "paused")
        self.assertEqual(first["summary"]["status_counts"]["found"], 500)

        final = adapter.resume()
        self.assertEqual(final["audit"]["cursor"], 501)
        self.assertEqual(final["audit"]["status"], "completed")
        self.assertEqual(final["summary"]["status_counts"]["found"], 501)
        self.assertEqual(
            {path: self.base.joinpath(*path.split("/")).read_bytes()
             for path in originals},
            originals,
        )
        saved = json.loads(adapter.ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(saved, final["audit"])
        self.assert_safe(saved)
        self.assert_safe(final)

    def test_reads_png_webp_json_and_never_persists_inspector_output(self):
        payloads = {
            "owned/a.png": bytes.fromhex("89504e470d0a") + b"png",
            "owned/b.webp": b"RIFFxxxxWEBPwebp",
            "owned/c.json": b'{"prompt":"private"}',
        }
        for relative, payload in payloads.items():
            self.write_owned(relative, payload)
        seen = []

        def inspector(payload, kind, path):
            seen.append((kind, path, bytes(payload)))
            return self.secret_inspector(payload, kind, path)

        adapter = MetadataAuditAdapter(
            self.base,
            metadata_inspector=inspector,
        )
        adapter.start(data_index([
            index_entry(path, payload) for path, payload in payloads.items()
        ]))
        result = adapter.run_chunk()
        self.assertEqual(
            [(kind, path) for kind, path, payload in seen],
            [
                ("png", "owned/a.png"),
                ("webp", "owned/b.webp"),
                ("json", "owned/c.json"),
            ],
        )
        self.assertEqual(
            [item["status"] for item in result["audit"]["items"]],
            ["found", "found", "found"],
        )
        for item in result["audit"]["items"]:
            self.assertEqual(
                set(item),
                {"path", "sha256", "kind", "status", "attempts", "error_code"},
            )
        self.assert_safe(result)
        self.assert_safe(
            json.loads(adapter.ledger_path.read_text(encoding="utf-8"))
        )

    def test_rejects_paths_outside_base_and_outside_ledger(self):
        outside_ledger = self.base.parent / "outside-ledger.json"
        with self.assertRaises(MetadataAuditPathError):
            MetadataAuditAdapter(
                self.base,
                metadata_inspector=self.secret_inspector,
                ledger_path=outside_ledger,
            )

        valid = b"valid"
        self.write_owned("owned/valid.png", valid)
        adapter = MetadataAuditAdapter(
            self.base,
            metadata_inspector=self.secret_inspector,
        )
        adapter.start(data_index([
            {"path": ABSOLUTE_PATH, "sha256": "a" * 64},
            {"path": "../outside.png", "sha256": "b" * 64},
            index_entry("owned/valid.png", valid),
        ]))
        result = adapter.run_chunk()
        self.assertEqual(
            [item["error_code"] for item in result["audit"]["items"][:2]],
            ["invalid-relative-path", "invalid-relative-path"],
        )
        self.assertEqual(result["audit"]["items"][2]["status"], "found")
        self.assert_safe(result)

    def test_pause_resume_missing_file_retry_and_content_sha_contract(self):
        first_payload = b"first"
        missing_payload = b"appears-later"
        self.write_owned("owned/first.webp", first_payload)
        entries = [
            index_entry("owned/first.webp", first_payload),
            index_entry("owned/later.json", missing_payload),
        ]
        adapter = MetadataAuditAdapter(
            self.base,
            metadata_inspector=self.secret_inspector,
        )
        adapter.start(data_index(entries))
        paused = adapter.pause()
        self.assertEqual(paused["audit"]["status"], "paused")
        unchanged = adapter.run_chunk()
        self.assertEqual(unchanged["audit"]["cursor"], 0)

        partial = adapter.resume()
        self.assertEqual(partial["audit"]["status"], "partial")
        self.assertEqual(
            [item["status"] for item in partial["audit"]["items"]],
            ["found", "error"],
        )
        self.assertEqual(
            partial["failures"][0]["path"],
            "owned/later.json",
        )

        self.write_owned("owned/later.json", missing_payload)
        final = adapter.retry(paths=["owned/later.json"])
        self.assertEqual(final["audit"]["status"], "completed")
        self.assertEqual(final["failures"], [])
        self.assertEqual(final["audit"]["items"][1]["attempts"], 2)
        self.assert_safe(final)

        self.write_owned("owned/first.webp", b"changed")
        restarted = adapter.start(data_index(entries))
        self.assertEqual(restarted["audit"]["cursor"], 0)
        changed = adapter.run_chunk()
        self.assertEqual(
            changed["audit"]["items"][0]["error_code"],
            "content-changed",
        )

    def test_atomic_replace_failure_keeps_previous_complete_ledger(self):
        payload = b"image"
        self.write_owned("owned/a.png", payload)
        adapter = MetadataAuditAdapter(
            self.base,
            metadata_inspector=self.secret_inspector,
        )
        adapter.start(data_index([index_entry("owned/a.png", payload)]))
        before = adapter.ledger_path.read_bytes()

        with patch.object(
            adapter_module.os,
            "replace",
            side_effect=OSError("simulated interruption"),
        ):
            with self.assertRaises(OSError):
                adapter.pause()

        self.assertEqual(adapter.ledger_path.read_bytes(), before)
        self.assertEqual(
            list(adapter.ledger_path.parent.glob("*.tmp")),
            [],
        )
        loaded = adapter.load()
        self.assertEqual(loaded["status"], "pending")
        self.assert_safe(loaded)

    def test_rejects_wrong_index_contract_without_creating_ledger(self):
        adapter = MetadataAuditAdapter(
            self.base,
            metadata_inspector=self.secret_inspector,
        )
        with self.assertRaises(MetadataAuditAdapterError):
            adapter.start({"schema": "other", "entries": []})
        with self.assertRaises(MetadataAuditAdapterError):
            adapter.start({"schema": DATA_INDEX_SCHEMA, "entries": {}})
        self.assertFalse(adapter.ledger_path.exists())


if __name__ == "__main__":
    unittest.main()
