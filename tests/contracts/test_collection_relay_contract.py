# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.nai_studio.services.collection_relay import (  # noqa: E402
    RELAY_ALLOWED_ORIGIN,
    RELAY_MAX_IMAGES,
    RelayPairing,
    handle_relay_payload,
)
from src.nai_studio.services.public_collection import (  # noqa: E402
    PublicCollectionManager,
)
from src.nai_studio.web.http_server import (  # noqa: E402
    ConfigRequestHandler,
)


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
ARTICLE_URL = "https://arca.live/b/aiart/12345"
HTML = (
    '<div class="article-content"><p>그림체 공유</p>'
    '<img src="https://ac.namu.la/x/abc.png"></div>'
)


def make_manager(temp_dir: Path) -> PublicCollectionManager:
    added = []
    manager = PublicCollectionManager(
        temp_dir / "공개자료수집-진행.json",
        style_record_from_image=lambda data, content_type, article: {
            "id": "arca-x",
            "url": article.get("source_url"),
            "images": [],
        },
        local_import_image=lambda data, content_type, url: (
            "local:abc.png", True),
        add_style_record=lambda record, import_info=None, return_detail=False: {
            "action": "added",
        },
    )
    manager._added_log = added
    return manager


class RelayPairingContractTests(unittest.TestCase):
    def test_codes_are_single_active_and_reissue_invalidates(self):
        pairing = RelayPairing()
        self.assertFalse(pairing.verify("AAAA-BBBB"))
        first = pairing.issue()["code"]
        self.assertTrue(pairing.verify(first))
        self.assertTrue(pairing.verify(first.lower()))
        second = pairing.issue()["code"]
        self.assertFalse(pairing.verify(first))
        self.assertTrue(pairing.verify(second))


class RelayPayloadContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nais-relay-")
        self.manager = make_manager(Path(self.temp.name))
        self.pairing = RelayPairing()
        self.code = self.pairing.issue()["code"]

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, **overrides):
        data = {
            "url": ARTICLE_URL,
            "html": HTML,
            "images": [{
                "type": "image/png",
                "data": base64.b64encode(PNG).decode("ascii"),
            }],
        }
        data.update(overrides)
        return data

    def relay(self, data=None, origin=RELAY_ALLOWED_ORIGIN, code=None):
        return handle_relay_payload(
            self.manager,
            self.pairing,
            data if data is not None else self.payload(),
            origin=origin,
            pairing_code=code if code is not None else self.code,
        )

    def test_valid_relay_lands_in_existing_collection_state(self):
        result = self.relay()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["classification"], "new")
        self.assertEqual(result["metadata_images"], 1)
        articles = self.manager.state["articles"]
        self.assertIn(ARTICLE_URL, articles)
        self.assertEqual(articles[ARTICLE_URL]["metadata_images"], 1)
        # 같은 내용을 다시 보내면 unchanged로 수렴한다
        again = self.relay()
        self.assertEqual(again["classification"], "unchanged")

    def test_wrong_origin_and_wrong_code_are_rejected(self):
        self.assertFalse(
            self.relay(origin="https://evil.example.com")["ok"])
        self.assertFalse(self.relay(code="0000-0000")["ok"])
        self.assertFalse(self.relay(code="")["ok"])
        self.assertNotIn(ARTICLE_URL, self.manager.state["articles"])

    def test_non_aiart_url_is_rejected(self):
        result = self.relay(self.payload(url="https://arca.live/b/free/1"))
        self.assertFalse(result["ok"])
        result = self.relay(
            self.payload(url="https://evil.example.com/b/aiart/1"))
        self.assertFalse(result["ok"])

    def test_image_type_and_magic_must_match(self):
        bad = self.payload(images=[
            {"type": "image/png",
             "data": base64.b64encode(b"not a png").decode("ascii")},
            {"type": "text/html",
             "data": base64.b64encode(PNG).decode("ascii")},
            {"type": "image/png",
             "data": base64.b64encode(PNG).decode("ascii")},
        ])
        result = self.relay(bad)
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["errors"]), 2)
        # 정상 이미지 하나는 들어갔다
        self.assertEqual(result["metadata_images"], 1)

    def test_image_count_cap(self):
        image = {
            "type": "image/png",
            "data": base64.b64encode(PNG).decode("ascii"),
        }
        result = self.relay(
            self.payload(images=[dict(image)] * (RELAY_MAX_IMAGES + 5)))
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("너무 많" in text for text in result["errors"]))

    def test_empty_html_is_rejected(self):
        self.assertFalse(self.relay(self.payload(html="  "))["ok"])


class RelayTransportContractTests(unittest.TestCase):
    def make_handler(self, path, headers):
        handler = object.__new__(ConfigRequestHandler)
        handler.path = path
        handler.headers = headers
        handler.server = SimpleNamespace(server_port=8787)
        return handler

    def test_relay_path_allows_arca_origin_only(self):
        base = {"Host": "127.0.0.1:8787", "Sec-Fetch-Site": "cross-site"}
        allowed = self.make_handler(
            "/api/public_collection_relay",
            {**base, "Origin": RELAY_ALLOWED_ORIGIN})
        self.assertTrue(allowed._trusted_post())
        wrong_origin = self.make_handler(
            "/api/public_collection_relay",
            {**base, "Origin": "https://evil.example.com"})
        self.assertFalse(wrong_origin._trusted_post())
        no_origin = self.make_handler(
            "/api/public_collection_relay", dict(base))
        self.assertFalse(no_origin._trusted_post())

    def test_other_paths_still_reject_cross_site(self):
        handler = self.make_handler("/api/save", {
            "Host": "127.0.0.1:8787",
            "Origin": RELAY_ALLOWED_ORIGIN,
            "Sec-Fetch-Site": "cross-site",
        })
        self.assertFalse(handler._trusted_post())
        # pairing 발급도 localhost 전용으로 남는다
        pairing = self.make_handler("/api/public_collection_pairing", {
            "Host": "127.0.0.1:8787",
            "Origin": RELAY_ALLOWED_ORIGIN,
        })
        self.assertFalse(pairing._trusted_post())

    def test_wrong_host_is_rejected_even_for_relay(self):
        handler = self.make_handler("/api/public_collection_relay", {
            "Host": "attacker.example.com:8787",
            "Origin": RELAY_ALLOWED_ORIGIN,
        })
        self.assertFalse(handler._trusted_post())


if __name__ == "__main__":
    unittest.main()
