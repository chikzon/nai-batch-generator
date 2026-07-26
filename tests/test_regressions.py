"""No-cost deterministic regressions for the local NAI helper.

These tests never call NovelAI. They cover failures found during the 2026-07
audit and are intentionally runnable with the Python standard test runner.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import socket
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nai_helper_under_test", ROOT / "start.py")
assert SPEC and SPEC.loader
APP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APP)


class RegressionTests(unittest.TestCase):
    def test_atomic_json_recovers_last_backup(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            APP.atomic_write_json(path, {"version": 1})
            APP.atomic_write_json(path, {"version": 2})
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(APP.load_json_recover(path), {"version": 1})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"version": 1})

    def test_numeric_values_are_clamped_and_invalid_text_is_rejected(self):
        cases = [
            ("steps", 999, 28, 50),
            ("cfg_scale", -5, 5.5, 1.0),
            ("cfg_rescale", 9, 0.56, 1.0),
            ("save_quality", 999, 92, 100),
            ("width", 777, 832, 768),
            ("height", 9999, 1216, 2048),
        ]
        for key, sent, current, expected in cases:
            ok, used, fixes = APP.validate_config_value(key, sent, current)
            self.assertTrue(ok, key)
            self.assertEqual(used, expected, key)
            self.assertIn(key, fixes)
        self.assertFalse(APP.validate_config_value("steps", "oops", 28)[0])

    def test_duplicate_cast_names_remain_distinct_resume_tasks(self):
        cfg = {"char_slots": [], "per_char_order": True}
        acfg = {"_settings": {"setting": {}}, "scenes": {"1": {"_setting": "setting"}}}
        state = {
            "use": True,
            "selected": ["group"],
            "cast": [
                {"name": "same", "prompt": "one", "negative": ""},
                {"name": "same", "prompt": "two", "negative": ""},
            ],
        }
        with (
            patch.object(APP, "setting_state", return_value=state),
            patch.object(APP, "derive_setting_catalog", return_value=[{"id": "group", "ids": [1]}]),
        ):
            pending = APP.compute_pending(cfg, acfg, {}, set())
            self.assertEqual(len(pending), 2)
            self.assertNotEqual(pending[0][1], pending[1][1])
            done = {pending[0][1]: {(1, 1)}}
            remaining = APP.compute_pending(cfg, acfg, done, set())
            self.assertEqual([(x[1], x[2], x[3]) for x in remaining],
                             [(pending[1][1], 1, 1)])

    def test_token_preview_expands_fragments_without_advancing_counters(self):
        cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
        cfg.update(use_fragments=True, _frag_counters={"long": 0})
        expansion = ", ".join(f"tag{i}" for i in range(900))
        with patch.object(APP, "list_fragments", return_value={"long": [expansion]}):
            final = APP.finalized_token_texts("<long>", "", [], [], cfg)
        self.assertGreater(APP.nai_tokens(final["base"]), 512)
        self.assertEqual(cfg["_frag_counters"], {"long": 0})

    def test_token_preview_includes_outfit_quality_and_uc_text(self):
        cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
        cfg.update(quality_toggle=True, uc_preset=0)
        final = APP.finalized_token_texts(
            "base", "custom negative", ["# memo\nface, red dress"], [""], cfg)
        self.assertIn("very aesthetic", final["base"])
        self.assertEqual(final["chars"], ["face, red dress"])
        self.assertNotIn("# memo", final["chars"][0])
        self.assertIn("custom negative", final["negative"])

    def test_resume_record_requires_existing_file_and_same_settings(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
            cfg["out_dir"] = td
            acfg = {"base": {"negative_prompt": "neg"},
                    "scenes": {"1": {"name": "scene"}}}
            char = {"name": "hero", "female": "face"}
            context = APP.generation_context_fingerprint(cfg, acfg)
            fingerprint = APP.generation_task_fingerprint(
                context, char, "hero-id", 1, 1)
            image = Path(td) / "nsfw_seed" / "image.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"image")
            record = APP.make_progress_record(cfg, 1, 1, image, fingerprint)
            self.assertTrue(APP.progress_record_valid(record, cfg, fingerprint))
            changed_cfg = copy.deepcopy(cfg)
            changed_cfg["base_prompt"] = "changed"
            changed_context = APP.generation_context_fingerprint(changed_cfg, acfg)
            changed_fingerprint = APP.generation_task_fingerprint(
                changed_context, char, "hero-id", 1, 1)
            self.assertNotEqual(fingerprint, changed_fingerprint)
            self.assertFalse(APP.progress_record_valid(record, cfg, changed_fingerprint))
            image.unlink()
            self.assertFalse(APP.progress_record_valid(record, cfg, fingerprint))

    def test_custom_output_root_and_date_are_used_by_batch_and_thumbnails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "chosen"
            cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
            cfg.update(out_dir=str(root), out_by_date=True)
            batch = APP.out_sub(cfg, "nsfw_seed")
            self.assertEqual(batch, root.resolve() / "nsfw_seed" / APP.date.today().isoformat())
            image = batch / "101_sample.webp"
            image.write_bytes(b"image")
            settings = [{"name": "S", "data": {"\uC52C": {"101": {}}}}]
            with (
                patch.object(APP, "list_settings", return_value=settings),
                patch.object(APP, "derive_setting_catalog",
                             return_value=[{"id": "G", "ids": [101]}]),
            ):
                self.assertEqual(
                    APP.setting_thumbs("S", cfg),
                    {"G": image.relative_to(root).as_posix()},
                )

    def test_local_http_rejects_cross_site_post_but_allows_local_cli(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
        server = APP.ConfigServer(cfg)
        with (
            patch.object(APP, "PREVIEW_PORT_RANGE", (port,)),
            patch.object(APP.webbrowser, "open", return_value=None),
        ):
            url = server.start()
        self.assertIsNotNone(url)
        payload = json.dumps({"base": "a", "chars": [], "negative": ""}).encode()

        def request(origin=None):
            headers = {"Content-Type": "application/json"}
            if origin:
                headers["Origin"] = origin
            req = urllib.request.Request(url + "api/tokens", data=payload, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=3) as response:
                    return response.status
            except urllib.error.HTTPError as exc:
                return exc.code

        try:
            self.assertEqual(request(), 200)
            self.assertEqual(request(url.rstrip("/")), 200)
            self.assertEqual(request("https://evil.example"), 403)
        finally:
            server.httpd.shutdown()
            server.httpd.server_close()


if __name__ == "__main__":
    unittest.main()
