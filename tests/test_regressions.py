"""No-cost deterministic regressions for the local NAI helper.

These tests never call NovelAI. They cover failures found during the 2026-07
audit and are intentionally runnable with the Python standard test runner.
"""

from __future__ import annotations

import copy
import io
import importlib.util
import json
import socket
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from PIL.PngImagePlugin import PngInfo


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nai_helper_under_test", ROOT / "start.py")
assert SPEC and SPEC.loader
APP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APP)


class RegressionTests(unittest.TestCase):
    def test_active_people_keep_slot_coordinate_pairs(self):
        slots = [
            {"prompt": "A", "negative": "na", "enabled": True},
            {"prompt": "B", "negative": "nb", "enabled": False},
            {"prompt": "# memo only", "negative": "nc", "enabled": True},
            {"prompt": "", "outfit": "red dress", "negative": "nd", "enabled": True},
            {"prompt": "C", "negative": "ne", "enabled": True},
        ]
        centers = [
            {"x": 0.1, "y": 0.2},
            {"x": 0.3, "y": 0.4},
            {"x": 0.5, "y": 0.6},
            {"x": 0.7, "y": 0.8},
            {"x": 0.9, "y": 0.1},
        ]
        people, used_centers = APP.active_people(slots, centers)
        self.assertEqual([x["prompt"] for x in people], ["A", "red dress", "C"])
        self.assertEqual(
            used_centers,
            [centers[0], centers[3], centers[4]],
        )

    def test_spread_centers_never_overlap_through_nai_limit(self):
        for count in range(2, APP.MAX_CHARS + 1):
            centers = APP.spread_centers(count)
            self.assertEqual(len(centers), count)
            self.assertEqual(
                len({(point["x"], point["y"]) for point in centers}),
                count,
            )

    def test_img2img_and_inpaint_are_not_reported_as_opus_free(self):
        cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
        cfg.update(width=832, height=1216, steps=28)
        self.assertTrue(APP.anlas_estimate(cfg, mode="t2i", opus=True)["free"])
        for mode in ("img2img", "infill"):
            estimate = APP.anlas_estimate(cfg, mode=mode, opus=True, strength=0.5)
            self.assertFalse(estimate["free"])
            self.assertGreater(estimate["total"], 0)

    def test_variety_sigma_tracks_model_generation(self):
        self.assertEqual(APP.variety_sigma("nai-diffusion-4-5-full"), 58.0)
        self.assertEqual(APP.variety_sigma("nai-diffusion-4-5-curated"), 58.0)
        self.assertEqual(APP.variety_sigma("nai-diffusion-4-full"), 19.0)
        self.assertEqual(APP.variety_sigma("nai-diffusion-3"), 19.0)
        with self.assertLogs(APP.log, level="WARNING") as captured:
            combined = APP._variety_sigma_value(
                "nai-diffusion-4-5-full",
                832,
                1216,
                True,
                {"_char_refs": {"images": ["fixture"]}},
            )
        self.assertEqual(combined, 58.0)
        self.assertIn("함께 보냅니다", "\n".join(captured.output))

    def test_pipe_tags_survive_inline_wildcard_expansion(self):
        """`{| |}`(23,000장)·`{|_|}` 는 실제 단부루 태그다 — 인라인 선택으로 오인해 지우면 안 된다."""
        for text in ("1girl, {| |}, smile", "1girl, {|_|}", "1girl, {a|}", "1girl, {|b}"):
            got, _ = APP.resolve_fragments([text], counters={})
            self.assertEqual(got[0], text, f"파이프 태그가 파괴됨: {text}")
        # 정상 인라인 선택은 계속 동작해야 한다
        got, _ = APP.resolve_fragments(["1girl, {red|blue|green}"], counters={})
        self.assertIn(got[0].rsplit(", ", 1)[-1], {"red", "blue", "green"})

    def test_tag_alias_autocomplete_returns_canonical_tag(self):
        data = {
            "rows": [
                ("1girl", 6008644, "", "general", ["1girls", "sole female"]),
                ("highres", 5256195, "", "meta", ["hires", "high resolution"]),
            ]
        }
        with (
            patch.object(APP, "_ac_cache_load", return_value=None),
            patch.object(APP, "_ac_cache_save"),
        ):
            index = APP._ac_index_inner(data)
        with patch.object(APP, "_ac_index", return_value=index):
            self.assertEqual(
                APP.autocomplete_tags({}, "1girls", 12)[0]["tag"],
                "1girl",
            )
            self.assertEqual(
                APP.autocomplete_tags({}, "sole female", 12)[0]["tag"],
                "1girl",
            )
            self.assertEqual(
                APP.autocomplete_tags({}, "hires", 12)[0]["tag"],
                "highres",
            )

    def test_disabled_coordinates_are_neutralized_in_actual_payload(self):
        png = io.BytesIO()
        Image.new("RGB", (2, 2), "white").save(png, "PNG")
        zipped = io.BytesIO()
        with zipfile.ZipFile(zipped, "w") as archive:
            archive.writestr("image.png", png.getvalue())

        class Response:
            status_code = 200
            content = zipped.getvalue()
            text = ""

        payloads = []

        def fake_post(_url, json=None, **_kwargs):
            payloads.append(json)
            return Response()

        base = {
            "model": "nai-diffusion-4-5-full",
            "char_centers": [{"x": 0.1, "y": 0.2}, {"x": 0.9, "y": 0.8}],
        }
        people = [
            {"prompt": "A", "negative": "na"},
            {"prompt": "B", "negative": "nb"},
        ]
        with patch.object(APP.requests, "post", side_effect=fake_post):
            APP.call_nai_api(
                "pst-fixture", "base", "", "", "negative", 832, 1216,
                seed=1, params={**base, "use_coords": False}, chars=people,
            )
            APP.call_nai_api(
                "pst-fixture", "base", "", "", "negative", 832, 1216,
                seed=1, params={**base, "use_coords": True}, chars=people,
            )

        def centers(payload, key):
            return [
                item["centers"][0]
                for item in payload["parameters"][key]["caption"]["char_captions"]
            ]

        neutral = [{"x": 0.5, "y": 0.5}, {"x": 0.5, "y": 0.5}]
        chosen = [{"x": 0.1, "y": 0.2}, {"x": 0.9, "y": 0.8}]
        self.assertEqual(centers(payloads[0], "v4_prompt"), neutral)
        self.assertEqual(centers(payloads[0], "v4_negative_prompt"), neutral)
        self.assertEqual(centers(payloads[1], "v4_prompt"), chosen)
        self.assertEqual(centers(payloads[1], "v4_negative_prompt"), chosen)

    def test_metadata_cleaning_removes_png_text_and_alpha_lsb(self):
        source = io.BytesIO()
        image = Image.new("RGBA", (2, 2), (10, 20, 30, 255))
        metadata = PngInfo()
        metadata.add_text("Comment", "private prompt")
        image.save(source, "PNG", pnginfo=metadata)

        cleaned, suffix = APP.strip_metadata(source.getvalue(), "fixture.png")
        self.assertEqual(suffix, ".png")
        with Image.open(io.BytesIO(cleaned)) as result:
            self.assertNotIn("Comment", result.info)
            self.assertTrue(all(alpha % 2 == 0 for alpha in result.getchannel("A").tobytes()))

    def test_metadata_import_strips_quality_suffix_and_restores_toggle(self):
        metadata = PngInfo()
        metadata.add_text(
            "Comment",
            json.dumps({
                "prompt": "1girl" + APP.QUALITY_SUFFIX,
                "uc": "bad anatomy",
                "seed": 1,
                "steps": 28,
                "width": 832,
                "height": 1216,
                "software": "NovelAI",
            }),
        )
        source = io.BytesIO()
        Image.new("RGB", (2, 2), "white").save(source, "PNG", pnginfo=metadata)

        with tempfile.TemporaryDirectory() as td, patch.object(APP, "IMG_CACHE", Path(td)):
            result = APP.ConfigServer(
                copy.deepcopy(APP.DEFAULT_CONFIG)
            ).handle_inspect(source.getvalue(), "fixture.png", "")
        self.assertTrue(result["ok"])
        self.assertEqual(result["style"]["base"], "1girl")
        self.assertTrue(result["style"]["params"]["quality_toggle"])
        self.assertEqual(result["style"]["negative"], "bad anatomy")

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

    def test_pace_gate_uses_completion_time_and_honors_cancel(self):
        cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
        cfg["pace"] = {
            "delay_min": 5,
            "delay_max": 5,
            "daily_cap": 100,
        }
        clock = [100.0]

        def fake_sleep(seconds):
            clock[0] += seconds

        class Live:
            stop_req = False

        APP._LAST_CALL["t"] = 0.0
        with (
            patch.object(APP, "load_state", return_value={"daily": {}}),
            patch.object(APP.random, "uniform", return_value=5.0),
            patch.object(APP.time, "time", side_effect=lambda: clock[0]),
            patch.object(APP.time, "sleep", side_effect=fake_sleep),
        ):
            self.assertEqual(APP.pace_gate(cfg, Live()), (True, ""))
            self.assertEqual(APP._LAST_CALL["t"], 0.0)
            APP.pace_complete()
            self.assertEqual(APP._LAST_CALL["t"], 100.0)

            clock[0] = 102.0
            self.assertEqual(APP.pace_gate(cfg, Live()), (True, ""))
            self.assertEqual(clock[0], 105.0)

            APP._LAST_CALL["t"] = 110.0
            stopped = Live()
            stopped.stop_req = True
            before = clock[0]
            ok, why = APP.pace_gate(cfg, stopped)
            self.assertFalse(ok)
            self.assertIn("중지", why)
            self.assertEqual(clock[0], before)

    def test_every_nai_generation_path_marks_completion(self):
        source = (ROOT / "start.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("call_nai_api("), 6)  # definition + five callers
        self.assertEqual(source.count("pace_complete()"), 6)  # definition + five callers
        self.assertNotIn(
            'time.sleep(random.uniform(pc["delay_min"], pc["delay_max"]))',
            source,
        )

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

    def test_output_listing_is_server_paginated_after_filters(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
            cfg["out_dir"] = td
            for index in range(305):
                image = root / f"{index:03d}.png"
                image.write_bytes(b"image")
                image.touch()
            picked = [f"{index:03d}.png" for index in range(0, 305, 2)]
            fav = [f"{index:03d}.png" for index in range(0, 305, 3)]
            labels = {"picked": picked, "fav": fav, "folders": {}, "ranks": {}}

            with patch.object(APP, "load_picks", return_value=labels):
                first = APP.list_output("", cfg, limit=120, offset=0)
                second = APP.list_output("", cfg, limit=120, offset=120)
                filtered = APP.list_output(
                    "", cfg, limit=500, offset=0, only_pick=True, only_fav=True
                )

            self.assertEqual(first["total"], 305)
            self.assertEqual(len(first["files"]), 120)
            self.assertTrue(first["has_more"])
            self.assertEqual(first["ranks"], {})
            self.assertEqual(second["offset"], 120)
            self.assertEqual(len(second["files"]), 120)
            self.assertTrue(
                {item["path"] for item in first["files"]}.isdisjoint(
                    item["path"] for item in second["files"]
                )
            )
            expected = set(picked) & set(fav)
            self.assertEqual(filtered["total"], len(expected))
            self.assertEqual({item["path"] for item in filtered["files"]}, expected)
            self.assertFalse(filtered["has_more"])

    def test_structured_diagnostics_redact_secrets_paths_and_export_safe_events(self):
        raw_lines = [
            (
                "2026-07-27 01:02:03,000 [INFO] 생성 저장 "
                r"C:\Users\alice\private\image.png token=pst-live-secret"
            ),
            (
                "2026-07-27 01:02:04,250 [ERROR] "
                "https://example.test/a?X-Amz-Signature=rawsig&key=rawkey "
                "Authorization: Bearer rawbearer"
            ),
            "Traceback (most recent call last):",
            (
                r'  File "C:\Users\alice\private\worker.py", line 7, in run '
                "token=pst-trace-secret"
            ),
        ]
        events = APP.parse_diagnostic_lines(raw_lines)
        exported = json.dumps(events, ensure_ascii=False)
        for secret in (
            "alice", "pst-live-secret", "pst-trace-secret",
            "rawsig", "rawkey", "rawbearer",
        ):
            self.assertNotIn(secret, exported)
        self.assertEqual(len(events), 2)
        self.assertIn(r"C:\\Users\\<user>", exported)
        self.assertIn("[REDACTED]", exported)
        self.assertIn("Traceback (most recent call last):", events[1]["message"])
        self.assertIn(r"C:\Users\<user>\private\worker.py", events[1]["message"])
        # 민감값이 있는 행은 기능 종류보다 보안 범주를 우선한다.
        self.assertEqual(events[0]["category"], "security")
        self.assertEqual(events[1]["category"], "security")
        self.assertEqual(events[1]["since_previous_ms"], 1250)
        self.assertIn("[ERROR][security]", APP.diagnostic_event_line(events[1]))

        with tempfile.TemporaryDirectory() as td:
            log_file = Path(td) / "fixture.log"
            log_file.write_text("\n".join(raw_lines), encoding="utf-8")
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            server = APP.ConfigServer(copy.deepcopy(APP.DEFAULT_CONFIG))
            with (
                patch.object(APP, "LOG_FILE", log_file),
                patch.object(APP, "PREVIEW_PORT_RANGE", (port,)),
                patch.object(APP.webbrowser, "open", return_value=None),
            ):
                url = server.start()
                try:
                    with urllib.request.urlopen(url + "api/diag?n=100", timeout=3) as response:
                        payload = json.loads(response.read())
                    with urllib.request.urlopen(
                        url + "api/diag?n=100&err=1", timeout=3
                    ) as response:
                        errors_only = json.loads(response.read())
                finally:
                    server.httpd.shutdown()
                    server.httpd.server_close()
        self.assertEqual(payload.get("schema"), "nais-diagnostics/v1", payload)
        self.assertEqual(len(payload["events"]), 2)
        self.assertEqual(len(errors_only["events"]), 1)
        self.assertEqual(errors_only["events"][0]["level"], "ERROR")
        api_text = json.dumps(payload, ensure_ascii=False)
        for secret in (
            "alice", "pst-live-secret", "pst-trace-secret",
            "rawsig", "rawkey", "rawbearer",
        ):
            self.assertNotIn(secret, api_text)
        self.assertIn("Traceback (most recent call last):", errors_only["events"][0]["message"])
        self.assertNotIn("toISOString().slice(0,10)", APP.PAGE_TEMPLATE)
        self.assertIn("getFullYear()", APP.PAGE_TEMPLATE)

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
