# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.nai_studio.services.update_check import (  # noqa: E402
    CURRENT_VERSION,
    UpdateCheckOperations,
    UpdateManager,
    parse_sha256sums,
    version_tuple,
)


SETUP_NAME = "NAI-batch-generator-9.9.9-setup.exe"
SETUP_BYTES = b"INSTALLER" * 100
SETUP_SHA = hashlib.sha256(SETUP_BYTES).hexdigest()

RELEASE = {
    "tag_name": "v9.9.9",
    "body": "고침: 무엇을 고쳤다\n둘째 줄",
    "published_at": "2026-08-01T00:00:00Z",
    "html_url": "https://github.com/chikzon/nai-batch-generator/releases/v9.9.9",
    "assets": [
        {
            "name": SETUP_NAME,
            "size": len(SETUP_BYTES),
            "browser_download_url": "https://github.com/dl/setup.exe",
        },
        {
            "name": "SHA256SUMS.txt",
            "size": 100,
            "browser_download_url": "https://github.com/dl/SHA256SUMS.txt",
        },
    ],
}


class FakeBackend:
    def __init__(self, root: Path):
        self.root = root
        self.release = dict(RELEASE)
        self.sums_text = f"{SETUP_SHA}  {SETUP_NAME}\n"
        self.offline = False
        self.download_calls = []
        self.installed = []

    def operations(self) -> UpdateCheckOperations:
        def http_get_json(url):
            if self.offline:
                raise ConnectionError("오프라인")
            return dict(self.release)

        def http_get_text(url):
            if self.offline:
                raise ConnectionError("오프라인")
            return self.sums_text

        def download(url, destination, *, expected_sha256):
            self.download_calls.append((url, str(destination), expected_sha256))
            if expected_sha256 != SETUP_SHA:
                return {"ok": False, "error": "해시 불일치"}
            Path(destination).parent.mkdir(parents=True, exist_ok=True)
            Path(destination).write_bytes(SETUP_BYTES)
            return {"ok": True, "path": str(destination), "sha256": SETUP_SHA}

        return UpdateCheckOperations(
            http_get_json=http_get_json,
            http_get_text=http_get_text,
            download=download,
            destination_root=lambda: self.root / "갱신",
            open_installer=lambda path: self.installed.append(str(path)),
        )


class UpdateCheckContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nais-update-")
        self.backend = FakeBackend(Path(self.temp.name))
        self.manager = UpdateManager(self.backend.operations)

    def tearDown(self):
        self.temp.cleanup()

    def wait_download(self):
        for _ in range(100):
            status = {**self.manager._state}
            if not status["downloading"]:
                return
            time.sleep(0.02)
        self.fail("다운로드가 끝나지 않았습니다")

    def test_version_constant_matches_build_metadata(self):
        from tools.build.app import APP_VERSION
        self.assertEqual(CURRENT_VERSION, APP_VERSION)

    def test_version_tuple_and_sums_parsing(self):
        self.assertGreater(version_tuple("v9.9.9"), version_tuple("1.1.0"))
        self.assertFalse(version_tuple("1.1.0") > version_tuple(CURRENT_VERSION))
        sums = parse_sha256sums(
            f"{'a'*64}  first.exe\n{'b'*64} *second.zip\n잘못된 줄\n")
        self.assertEqual(sums, {"first.exe": "a" * 64, "second.zip": "b" * 64})

    def test_status_shows_versions_notes_and_size_first(self):
        status = self.manager.status()
        self.assertTrue(status["ok"])
        self.assertEqual(status["current"], CURRENT_VERSION)
        self.assertEqual(status["latest"], "9.9.9")
        self.assertTrue(status["update_available"])
        self.assertEqual(status["download_size"], len(SETUP_BYTES))
        self.assertIn("고침", status["notes"])
        self.assertFalse(status["downloading"])

    def test_offline_keeps_current_version_quietly(self):
        self.backend.offline = True
        status = self.manager.status()
        self.assertFalse(status["ok"])
        self.assertEqual(status["current"], CURRENT_VERSION)
        self.assertIn("확인하지 못했습니다", status["error"])

    def test_download_completes_only_when_sums_match(self):
        result = self.manager.download()
        self.assertTrue(result["ok"], result)
        self.wait_download()
        state = self.manager._state
        self.assertTrue(state["download_result"]["ok"])
        self.assertEqual(state["downloaded"]["sha256"], SETUP_SHA)
        self.assertEqual(
            self.backend.download_calls[0][2], SETUP_SHA)

    def test_missing_sums_entry_refuses_download(self):
        self.backend.sums_text = f"{'c'*64}  다른파일.zip\n"
        result = self.manager.download()
        self.assertFalse(result["ok"])
        self.assertIn("SHA256SUMS", result["error"])
        self.assertEqual(self.backend.download_calls, [])

    def test_same_version_release_is_not_downloaded(self):
        self.backend.release = {
            **RELEASE,
            "tag_name": f"v{CURRENT_VERSION}",
        }
        result = self.manager.download()
        self.assertFalse(result["ok"])
        self.assertIn("최신", result["error"])

    def test_install_requires_verified_download(self):
        refused = self.manager.install()
        self.assertFalse(refused["ok"])
        self.manager.download()
        self.wait_download()
        done = self.manager.install()
        self.assertTrue(done["ok"], done)
        self.assertEqual(len(self.backend.installed), 1)
        self.assertTrue(self.backend.installed[0].endswith(SETUP_NAME))

    def test_tampered_installer_is_never_launched(self):
        self.manager.download()
        self.wait_download()
        path = Path(self.manager._state["downloaded"]["path"])
        path.write_bytes(b"tampered")
        result = self.manager.install()
        self.assertFalse(result["ok"])
        self.assertEqual(self.backend.installed, [])

    def test_existing_verified_file_is_reused_without_network_download(self):
        destination = self.backend.root / "갱신" / SETUP_NAME
        destination.parent.mkdir(parents=True)
        destination.write_bytes(SETUP_BYTES)
        result = self.manager.download()
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("reused"))
        self.assertEqual(self.backend.download_calls, [])
        self.assertTrue(self.manager.install()["ok"])


if __name__ == "__main__":
    unittest.main()
