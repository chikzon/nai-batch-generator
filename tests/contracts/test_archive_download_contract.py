# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.nai_studio.runtime.data_files import (  # noqa: E402
    atomic_write_json,
    load_json_recover,
)
from src.nai_studio.services.archive_download import (  # noqa: E402
    ArchiveDownloadError,
    ArchiveDownloadOperations,
    download_archive,
    validate_archive_url,
)


PAYLOAD = bytes(range(256)) * 512  # 128KiB
URL = "https://files.example.com/pack.zip"


class FakeResponse:
    def __init__(self, status, headers, body: bytes, fail_after: int = -1):
        self.status_code = status
        self.headers = headers
        self._body = body
        self._fail_after = fail_after

    def iter_content(self, chunk_size):
        sent = 0
        for start in range(0, len(self._body), chunk_size):
            if self._fail_after >= 0 and sent >= self._fail_after:
                raise ConnectionError("연결 끊김")
            chunk = self._body[start:start + chunk_size]
            sent += len(chunk)
            yield chunk

    def close(self):
        pass


class FakeServer:
    """Range를 지원하는 파일 서버 흉내. ETag·Last-Modified를 돌려준다."""

    def __init__(self, body=PAYLOAD, etag='"v1"', supports_range=True):
        self.body = body
        self.etag = etag
        self.supports_range = supports_range
        self.fail_after = -1
        self.requests: list[dict] = []

    def open_stream(self, url, headers):
        self.requests.append({"url": url, "headers": dict(headers)})
        base = {
            "ETag": self.etag,
            "Last-Modified": "Wed, 30 Jul 2026 00:00:00 GMT",
        }
        range_header = str(headers.get("Range") or "")
        if range_header and self.supports_range:
            start = int(range_header.split("=")[1].rstrip("-"))
            body = self.body[start:]
            return FakeResponse(206, {
                **base,
                "Content-Length": str(len(body)),
                "Content-Range": f"bytes {start}-{len(self.body)-1}"
                f"/{len(self.body)}",
            }, body, self.fail_after)
        return FakeResponse(200, {
            **base,
            "Content-Length": str(len(self.body)),
        }, self.body, self.fail_after)


class ArchiveDownloadContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nais-dl-")
        self.dest = Path(self.temp.name) / "받기" / "pack.zip"
        self.server = FakeServer()

    def tearDown(self):
        self.temp.cleanup()

    def operations(self, server=None, should_stop=None):
        server = server or self.server
        return ArchiveDownloadOperations(
            open_stream=server.open_stream,
            resolve_host=lambda host: ["93.184.216.34"],
            atomic_write_json=atomic_write_json,
            load_json=load_json_recover,
            should_stop=should_stop or (lambda: False),
        )

    def sidecar(self) -> Path:
        return self.dest.with_name(self.dest.name + ".download.json")

    def part(self) -> Path:
        return self.dest.with_name(self.dest.name + ".part")

    def test_full_download_verifies_hash_and_cleans_sidecar(self):
        digest = hashlib.sha256(PAYLOAD).hexdigest()
        result = download_archive(
            self.operations(), URL, self.dest,
            expected_sha256=digest, chunk_size=16384)
        self.assertTrue(result["ok"])
        self.assertEqual(self.dest.read_bytes(), PAYLOAD)
        self.assertEqual(result["sha256"], digest)
        self.assertFalse(self.part().exists())
        self.assertFalse(self.sidecar().exists())

    def test_interrupted_download_resumes_with_range(self):
        self.server.fail_after = 65536
        with self.assertRaises(ConnectionError):
            download_archive(
                self.operations(), URL, self.dest,
                chunk_size=16384, checkpoint_bytes=16384)
        state = load_json_recover(self.sidecar())
        self.assertGreaterEqual(state["received"], 16384)
        self.server.fail_after = -1
        result = download_archive(
            self.operations(), URL, self.dest, chunk_size=16384)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["resumed"])
        self.assertEqual(self.dest.read_bytes(), PAYLOAD)
        # 이어받기 요청이 실제 Range로 나갔다
        range_requests = [
            item for item in self.server.requests
            if item["headers"].get("Range")
        ]
        self.assertTrue(range_requests)

    def test_stop_request_leaves_resumable_state(self):
        calls = {"n": 0}

        def stop_after_two():
            calls["n"] += 1
            return calls["n"] > 2

        result = download_archive(
            self.operations(should_stop=stop_after_two), URL, self.dest,
            chunk_size=16384, checkpoint_bytes=16384)
        self.assertFalse(result["ok"])
        self.assertTrue(result["resumable"])
        self.assertTrue(self.sidecar().exists())
        result = download_archive(
            self.operations(), URL, self.dest, chunk_size=16384)
        self.assertTrue(result["ok"])
        self.assertEqual(self.dest.read_bytes(), PAYLOAD)

    def test_changed_etag_restarts_from_zero(self):
        self.server.fail_after = 65536
        with self.assertRaises(ConnectionError):
            download_archive(
                self.operations(), URL, self.dest,
                chunk_size=16384, checkpoint_bytes=16384)
        # 서버 내용이 바뀜 (ETag 변경 + 내용 교체)
        new_body = b"Z" * len(PAYLOAD)
        self.server.body = new_body
        self.server.etag = '"v2"'
        self.server.fail_after = -1
        result = download_archive(
            self.operations(), URL, self.dest, chunk_size=16384)
        self.assertTrue(result["ok"])
        self.assertFalse(result["resumed"])
        self.assertEqual(self.dest.read_bytes(), new_body)

    def test_server_without_range_support_restarts_cleanly(self):
        self.server.fail_after = 65536
        with self.assertRaises(ConnectionError):
            download_archive(
                self.operations(), URL, self.dest,
                chunk_size=16384, checkpoint_bytes=16384)
        self.server.supports_range = False
        self.server.fail_after = -1
        result = download_archive(
            self.operations(), URL, self.dest, chunk_size=16384)
        self.assertTrue(result["ok"])
        self.assertFalse(result["resumed"])
        self.assertEqual(self.dest.read_bytes(), PAYLOAD)

    def test_tampered_part_file_restarts_instead_of_mixing(self):
        self.server.fail_after = 65536
        with self.assertRaises(ConnectionError):
            download_archive(
                self.operations(), URL, self.dest,
                chunk_size=16384, checkpoint_bytes=16384)
        raw = self.part().read_bytes()
        self.part().write_bytes(b"X" + raw[1:])
        self.server.fail_after = -1
        result = download_archive(
            self.operations(), URL, self.dest, chunk_size=16384)
        self.assertTrue(result["ok"])
        self.assertFalse(result["resumed"])
        self.assertEqual(self.dest.read_bytes(), PAYLOAD)

    def test_size_cap_rejects_oversized_archives(self):
        result = download_archive(
            self.operations(), URL, self.dest,
            max_bytes=1024, chunk_size=16384)
        self.assertFalse(result["ok"])
        self.assertFalse(result["resumable"])
        self.assertFalse(self.dest.exists())

    def test_wrong_final_hash_discards_everything(self):
        result = download_archive(
            self.operations(), URL, self.dest,
            expected_sha256="f" * 64, chunk_size=16384)
        self.assertFalse(result["ok"])
        self.assertFalse(self.part().exists())
        self.assertFalse(self.sidecar().exists())
        self.assertFalse(self.dest.exists())

    def test_https_and_public_hosts_only(self):
        resolve = lambda host: ["93.184.216.34"]  # noqa: E731
        with self.assertRaises(ArchiveDownloadError):
            validate_archive_url("http://files.example.com/a.zip", resolve)
        with self.assertRaises(ArchiveDownloadError):
            validate_archive_url("https://127.0.0.1/a.zip", resolve)
        with self.assertRaises(ArchiveDownloadError):
            validate_archive_url("https://[::1]/a.zip", resolve)
        with self.assertRaises(ArchiveDownloadError):
            validate_archive_url(
                "https://internal.example.com/a.zip",
                lambda host: ["192.168.0.10"])
        self.assertEqual(
            validate_archive_url("https://files.example.com/a.zip", resolve),
            "https://files.example.com/a.zip")

    def test_redirect_to_private_address_is_blocked(self):
        hops = {"n": 0}

        def open_stream(url, headers):
            hops["n"] += 1
            if hops["n"] == 1:
                return FakeResponse(302, {
                    "Location": "https://internal.example.com/a.zip",
                }, b"")
            raise AssertionError("차단됐어야 한다")

        def resolve(host):
            return (
                ["93.184.216.34"]
                if host == "files.example.com"
                else ["10.0.0.5"]
            )

        operations = ArchiveDownloadOperations(
            open_stream=open_stream,
            resolve_host=resolve,
            atomic_write_json=atomic_write_json,
            load_json=load_json_recover,
        )
        result = None
        with self.assertRaises(ArchiveDownloadError):
            result = download_archive(operations, URL, self.dest)
        self.assertIsNone(result)


class ArchiveDownloadManagerContractTests(unittest.TestCase):
    def setUp(self):
        import threading

        from src.nai_studio.services.archive_download import (
            ArchiveDownloadManager,
        )

        self.temp = tempfile.TemporaryDirectory(prefix="nais-dlm-")
        self.root = Path(self.temp.name) / "수집" / "받기"
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list = []

        def fake_download(operations, url, destination, **kwargs):
            self.calls.append((url, str(destination), kwargs))
            self.started.set()
            self.release.wait(timeout=5)
            if operations.should_stop():
                return {"ok": False, "resumable": True, "error": "중지"}
            return {"ok": True, "path": str(destination), "bytes": 3}

        def operations_factory(should_stop):
            return ArchiveDownloadOperations(
                open_stream=lambda url, headers: None,
                resolve_host=lambda host: ["93.184.216.34"],
                atomic_write_json=atomic_write_json,
                load_json=load_json_recover,
                should_stop=should_stop,
            )

        self.manager = ArchiveDownloadManager(
            destination_root=lambda: self.root,
            operations_factory=operations_factory,
            download=fake_download,
        )

    def tearDown(self):
        self.release.set()
        self.temp.cleanup()

    def wait_done(self):
        for _ in range(100):
            if not self.manager.snapshot()["running"]:
                return
            import time
            time.sleep(0.02)
        self.fail("작업이 끝나지 않았습니다")

    def test_start_stop_status_round_trip(self):
        result = self.manager.control({"action": "start", "url": URL})
        self.assertTrue(result["ok"], result)
        self.assertTrue(self.started.wait(timeout=5))
        status = self.manager.control({"action": "status"})
        self.assertTrue(status["running"])
        # 진행 중 중복 시작 거부
        again = self.manager.control({"action": "start", "url": URL})
        self.assertFalse(again["ok"])
        stop = self.manager.control({"action": "stop"})
        self.assertTrue(stop["ok"])
        self.release.set()
        self.wait_done()
        status = self.manager.control({"action": "status"})
        self.assertFalse(status["running"])
        self.assertTrue(status["result"]["resumable"])
        # 끝난 뒤 재시작 가능
        self.release.clear()
        self.started.clear()
        result = self.manager.control({"action": "start", "url": URL})
        self.assertTrue(result["ok"])
        self.release.set()
        self.wait_done()

    def test_bad_url_is_rejected_before_thread_starts(self):
        result = self.manager.control(
            {"action": "start", "url": "http://files.example.com/a.zip"})
        self.assertFalse(result["ok"])
        self.assertFalse(self.manager.snapshot()["running"])

    def test_filename_escape_is_rejected(self):
        result = self.manager.control({
            "action": "start",
            "url": URL,
            "filename": "..\\밖.zip",
        })
        self.assertFalse(result["ok"])

    def test_unknown_action_is_rejected(self):
        result = self.manager.control({"action": "fly"})
        self.assertFalse(result["ok"])


class ArchiveDownloadRouteContractTests(unittest.TestCase):
    def test_collection_post_routes_control_body(self):
        from src.nai_studio.web.routes.collection_post import (
            CollectionPostOperations,
            handle_collection_post,
        )

        class FakeRequest:
            path = "/api/archive_download_control"
            headers: dict = {}

            def __init__(self):
                self.sent = None

            def _json(self, payload):
                self.sent = payload

        log: list = []
        operations = CollectionPostOperations(
            preview_pack=None,
            import_pack=None,
            pack_queue=None,
            summarize_queue=None,
            forget_caches=None,
            load_spec=None,
            options=None,
            load_options=None,
            public_start=None,
            public_retry=None,
            public_control=None,
            undo_pack=None,
            import_settings=None,
            resource_import=None,
            reference_add=None,
            reference_save=None,
            archive_download_control=lambda data: (
                log.append(data), {"ok": True, "echo": data})[1],
        )
        request = FakeRequest()
        handled = handle_collection_post(
            request, None, operations,
            b'{"action": "status"}')
        self.assertTrue(handled)
        self.assertTrue(request.sent["ok"])
        self.assertEqual(log, [{"action": "status"}])


if __name__ == "__main__":
    unittest.main()
