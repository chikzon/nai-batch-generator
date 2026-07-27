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

    def test_opus_character_reference_keeps_free_generation_and_costs_five_each(self):
        cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
        cfg.update(width=832, height=1216, steps=28)
        estimate = APP.anlas_estimate(
            cfg, count=3, mode="t2i", opus=True, char_refs=1)
        self.assertTrue(estimate["generation_free"])
        self.assertFalse(estimate["free"])
        self.assertEqual(estimate["char_ref_fee"], 5)
        self.assertEqual(estimate["per_image"], 5)
        self.assertEqual(estimate["total"], 15)
        self.assertIn("Opus 무료 생성", estimate["why"])

    def test_anlas_reason_does_not_blame_free_size_when_tier_is_unknown(self):
        cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
        cfg.update(width=832, height=1216, steps=28)
        estimate = APP.anlas_estimate(cfg, opus=False)
        self.assertFalse(estimate["free"])
        self.assertIn("Opus 적용 여부", estimate["why"])
        self.assertNotIn("무료 조건 초과", estimate["why"])

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

    def test_runtime_reference_params_replace_stale_state_without_mutating_cfg(self):
        cfg = {
            "_vibes": {"encoded": ["stale-vibe"]},
            "_char_refs": {"images": ["stale-ref"]},
            "vibes": [],
            "char_refs": [],
        }
        with (
            patch.object(
                APP,
                "prepare_vibes",
                return_value=(["fresh-vibe"], [0.7], [0.8], 0),
            ),
            patch.object(
                APP,
                "prepare_char_refs",
                return_value=(["fresh-ref"], ["character&style"], [0.6], [0.5]),
            ),
        ):
            params = APP.runtime_generation_params(cfg, "pst-test")

        self.assertEqual(params["_vibes"]["encoded"], ["fresh-vibe"])
        self.assertEqual(params["_char_refs"]["images"], ["fresh-ref"])
        self.assertEqual(cfg["_vibes"]["encoded"], ["stale-vibe"])
        self.assertEqual(cfg["_char_refs"]["images"], ["stale-ref"])

        restored = APP.runtime_generation_params(cfg, "pst-test", include_refs=False)
        self.assertNotIn("_vibes", restored)
        self.assertNotIn("_char_refs", restored)

    def test_restore_model_mapping_ignores_source_build_hash_digits(self):
        fallback = "nai-diffusion-4-5-curated"
        cases = {
            "NovelAI Diffusion V4.5 4BDE2A90": "nai-diffusion-4-5-full",
            "NAI Diffusion 4.5 Curated": "nai-diffusion-4-5-curated",
            "NAI Diffusion V4 Full": "nai-diffusion-4-full",
            "NAI Diffusion V4 Curated": "nai-diffusion-4-curated-preview",
            "NovelAI Diffusion Furry V3": "nai-diffusion-furry-3",
            "Stable Diffusion XL 9CC2F394": "nai-diffusion-3",
            "Stable Diffusion XL C1E1DE52": "nai-diffusion-3",
            "Stable Diffusion 1D44365E": fallback,
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(
                    APP.model_id_from_metadata(source, fallback),
                    expected,
                )

    def test_quality_and_uc_text_are_model_specific_and_round_trip(self):
        self.assertNotIn(
            "location", APP.QUALITY_SUFFIX_TEXT["nai-diffusion-4-5-full"])
        for model, quality in APP.QUALITY_SUFFIX_TEXT.items():
            with self.subTest(model=model, kind="quality"):
                merged = APP.merge_quality_suffix("user prompt", model)
                self.assertEqual(merged, f"user prompt, {quality}")
                self.assertEqual(
                    APP.split_quality_suffix(merged, model),
                    ("user prompt", True),
                )

        v45 = "nai-diffusion-4-5-full"
        heavy = APP.uc_preset_text(v45, 0)
        self.assertTrue(heavy.startswith("lowres, artistic error"))
        self.assertNotIn("nsfw", heavy)
        merged_uc = APP.merge_uc_preset("nsfw, custom tag", v45, 0)
        self.assertEqual(
            APP.split_uc_preset(merged_uc, v45),
            (0, "nsfw, custom tag"),
        )

        # 같은 UI 번호라도 모델마다 공식 문구가 다르다.
        self.assertNotEqual(
            APP.uc_preset_text("nai-diffusion-4-5-full", 0),
            APP.uc_preset_text("nai-diffusion-4-full", 0),
        )
        # V4 Full에는 Human Focus 공식 프리셋이 없으므로 V4.5 값을 대신 넣지 않는다.
        self.assertEqual(APP.uc_preset_text("nai-diffusion-4-full", 3), "")

    def test_saved_comment_embeds_quality_and_uc_state_for_exact_restore(self):
        original = json.dumps({
            "prompt": "1girl, very aesthetic, masterpiece, no text",
            "uc": "lowres",
            "source": "NovelAI Diffusion V4.5",
            "steps": 28,
        })
        annotated = APP.annotate_nai_comment(original, True, 3)
        values = json.loads(annotated)
        self.assertTrue(values["qualityToggle"])
        self.assertEqual(values["ucPreset"], 3)

        image = Image.new("RGB", (2, 2), "white")
        metadata = PngInfo()
        metadata.add_text("Comment", annotated)
        blob = io.BytesIO()
        image.save(blob, "PNG", pnginfo=metadata)
        extracted = APP.extract_nai_metadata(blob.getvalue(), "image/png")
        self.assertTrue(extracted["params"]["quality_toggle"])
        self.assertEqual(extracted["params"]["uc_preset"], 3)

    def test_retry_after_and_http_retryability_are_classified(self):
        self.assertEqual(APP.retry_after_seconds("7"), 7)

        class Response:
            content = b""
            text = "fixture"
            headers = {}

        bad_request = Response()
        bad_request.status_code = 400
        with patch.object(APP.requests, "post", return_value=bad_request):
            with self.assertRaises(APP.APIError) as caught:
                APP.call_nai_api(
                    "pst-fixture", "base", "", "", "negative", 832, 1216)
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(caught.exception.status_code, 400)

        limited = Response()
        limited.status_code = 429
        limited.headers = {"Retry-After": "3"}
        with patch.object(APP.requests, "post", return_value=limited):
            with self.assertRaises(APP.RateLimitError) as caught:
                APP.call_nai_api(
                    "pst-fixture", "base", "", "", "negative", 832, 1216)
        self.assertEqual(caught.exception.retry_after, 3)

    def test_output_delete_moves_to_recoverable_trash_and_restores_without_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "output"
            source = root / "단독" / "one.png"
            outside = Path(td) / "outside.png"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"old")
            outside.write_bytes(b"outside")
            cfg = {"out_dir": str(root)}

            result = APP.trash_output_files(
                cfg, ["단독/one.png", "../outside.png"])
            self.assertEqual(result["deleted"], 1)
            self.assertFalse(source.exists())
            self.assertEqual(outside.read_bytes(), b"outside")
            listing = APP.list_output("", cfg)
            self.assertNotIn(
                APP.TRASH_DIR_NAME, [item["name"] for item in listing["dirs"]])
            self.assertFalse(
                APP.list_output(APP.TRASH_DIR_NAME, cfg)["ok"])

            # 같은 이름이 다시 생겨도 복원 파일로 덮어쓰지 않는다.
            source.write_bytes(b"new")
            restored = APP.restore_trash_batch(cfg, result["batch_id"])
            self.assertEqual(restored["restored"], 1)
            self.assertEqual(source.read_bytes(), b"new")
            restored_path = root / restored["paths"][0]
            self.assertEqual(restored_path.read_bytes(), b"old")

    def test_setout_serves_normal_output_but_blocks_trashed_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "output"
            safe = root / "safe.png"
            trashed = root / APP.TRASH_DIR_NAME / "batch" / "hidden.png"
            safe.parent.mkdir(parents=True)
            trashed.parent.mkdir(parents=True)
            safe.write_bytes(b"safe")
            trashed.write_bytes(b"hidden")
            cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
            cfg["out_dir"] = str(root)

            self.assertEqual(APP.output_file_for_preview(cfg, "safe.png"), safe)
            self.assertIsNone(APP.output_file_for_preview(
                cfg, f"{APP.TRASH_DIR_NAME}/batch/hidden.png"))
            self.assertIsNone(APP.output_file_for_preview(
                cfg, ".nai-휴지통/batch/hidden.png"))
            self.assertIsNone(APP.output_file_for_preview(
                cfg, f"{APP.TRASH_DIR_NAME}/../safe.png"))

            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            server = APP.ConfigServer(cfg)
            with (
                patch.object(APP, "PREVIEW_PORT_RANGE", (port,)),
                patch.object(APP.webbrowser, "open", return_value=None),
            ):
                url = server.start()
            try:
                with urllib.request.urlopen(url + "setout?p=safe.png", timeout=3) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.read(), b"safe")
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(
                        url + "setout?p=.NAI-%ED%9C%B4%EC%A7%80%ED%86%B5/"
                        "batch/hidden.png", timeout=3)
                self.assertEqual(denied.exception.code, 404)
                with self.assertRaises(urllib.error.HTTPError) as denied_lower:
                    urllib.request.urlopen(
                        url + "setout?p=.nai-%ED%9C%B4%EC%A7%80%ED%86%B5/"
                        "batch/hidden.png", timeout=3)
                self.assertEqual(denied_lower.exception.code, 404)
            finally:
                server.httpd.shutdown()
                server.httpd.server_close()

    def test_every_generation_path_builds_call_local_reference_params(self):
        source = (ROOT / "start.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("runtime_generation_params("), 6)
        self.assertNotIn('raw.get("source_model")', source)
        self.assertNotIn("ensure_refs(", source)

    def test_page_installs_visible_runtime_error_handlers_before_app_code(self):
        page = APP.render_page()
        handlers_at = page.index("window.addEventListener('error'")
        state_at = page.index("let STATE = null")
        self.assertLess(handlers_at, state_at)
        self.assertIn("window.addEventListener('unhandledrejection'", page)
        self.assertIn("fatalErrorBar", page)
        self.assertIn("새로고침", page)

    def test_collapsible_panels_pin_their_grid_columns(self):
        """패널을 접어도 가운데가 밀리지 않게 **열을 못박아** 둔다.

        `display:none` 은 항목을 격자 흐름에서 뺀다. 세 패널의 `grid-column` 을
        정해 두지 않으면 좌패널을 접었을 때 자동 배치가 한 칸씩 당겨져 가운데가
        1번 열(0px)로 밀리고 오른쪽이 `1fr` 을 가져간다 — 브라우저 실측에서
        중 860→48 · 우 300→1300 이었다. 화면 없이도 지킬 수 있게 여기서 막는다."""
        page = APP.render_page()
        squished = page.replace(" ", "")
        # ⚠ 실패해도 페이지를 통째로 덤프하지 않게 참/거짓으로 잰다 (300KB 가 쏟아진다)
        for sel in (".left{grid-column:1;}", ".center{grid-column:2;}",
                    ".right{grid-column:3;}"):
            self.assertTrue(sel in squished, f"패널 열이 안 박혀 있다: {sel}")
        # 접기는 열 폭 변수만 0 으로 바꾼다 (반응형 폭 단계를 덮어쓰지 않는다)
        for sel in ('#app[data-lhide="1"]{--colL:0;}', '#app[data-rhide="1"]{--colR:0;}',
                    "grid-template-columns:var(--colL)"):
            self.assertTrue(sel in squished, f"접기 규칙이 없다: {sel}")
        # 토글 단추와 상태 저장이 함께 있어야 실제로 쓸 수 있다
        for sel in ('id="togLeft"', 'id="togRight"', "localStorage.setItem(key"):
            self.assertTrue(sel in page, f"패널 접기 조작부가 없다: {sel}")

    def test_explorer_bar_has_a_single_auto_margin_and_regen_is_its_own_card(self):
        """한 줄에 `margin-left:auto` 를 **둘** 두면 무엇이 한 묶음인지 안 읽힌다.

        `.bar .n{margin-left:auto}` 에 더해 `expCompare` 에도 auto 가 붙어 있어서
        상태글이 줄 한복판에 뜨고 단추가 좌우로 흩어졌다. 지금은 auto 가 `expStat`
        하나뿐이라 [고르는 도구들] … 상태 [선별 외 삭제] 로 읽힌다.

        그림체 복구는 **고르는 일이 아니라 새로 뽑는 일**이라(결과가 `output/복구/` 에
        쌓이고 Anlas 도 든다) 카드를 갈랐다."""
        page = APP.render_page()
        bar_at = page.index('id="expCup"')
        bar_end = page.index("</div>", bar_at)
        bar = page[bar_at:bar_end]
        self.assertFalse("margin-left:auto" in bar,
                         "탐색기 단추 줄에 auto 여백이 다시 생겼다 (상태글의 것 하나면 된다)")
        # 파괴적 동작은 남기되 상태글 뒤로 떼어 놓는다 (없애지 않는다)
        self.assertTrue(page.index('id="expStat"') < page.index('id="expDelUnpicked"'),
                        "`선별 외 삭제` 가 다른 단추 옆으로 붙었다")
        self.assertTrue('id="expDelUnpicked"' in page and 'class="danger"' in page,
                        "`선별 외 삭제` 가 사라졌거나 경고색을 잃었다")
        # 복구는 탐색기와 다른 카드에 있어야 한다
        self.assertTrue(page.index('id="expGrid"') < page.index('id="regenMode"'),
                        "그림체 복구가 다시 탐색기 카드 안으로 들어갔다")
        for sel in ('id="regenMode"', 'id="regenStrength"', 'id="regenPicked"', 'id="regenAll"'):
            self.assertTrue(sel in page, f"복구 조작부가 사라졌다: {sel}")

    def test_destructive_buttons_are_not_adjacent_to_creating_ones(self):
        """되돌릴 수 없는 단추를 만드는 단추 **바로 옆**에 두지 않는다.

        `선별 외 삭제`·`꺼진 칸 정리`·`세팅 삭제` 는 각각 파일·칸·씬 수백 개를
        지운다. `+ 새 세팅` 이나 `⧉ 복제` 옆에 붙어 있으면 손이 미끄러진다.
        단추를 없애거나 빨간색을 빼지 않는다 — **자리만** 떼어 놓는다."""
        page = APP.render_page()
        for bid in ('id="slotDelOff"', 'id="sbDel"', 'id="expDelUnpicked"'):
            self.assertTrue(bid in page, f"파괴적 단추가 사라졌다: {bid}")
        # 빨간 경고색은 유지해야 한다
        for bid in ("slotDelOff", "sbDel", "expDelUnpicked"):
            at = page.index(f'id="{bid}"')
            near = page[max(0, at - 160):at + 160]
            self.assertTrue("danger" in near, f"`{bid}` 가 경고색을 잃었다")
        # 자리를 벌리는 장치가 있어야 한다.
        # ⚠ `<span style="flex:1">` 스페이서는 쓰지 않는다 — `.bar` 가 `flex-wrap:wrap` 이라
        #   좁은 오버레이에서 단추를 다음 줄 **왼쪽 끝**으로 밀어낸다(실측 x=12).
        #   `margin-left:auto` 는 어느 줄에 놓이든 그 줄 오른쪽 끝으로 간다.
        for bid in ("slotDelOff", "sbDel"):
            at = page.index(f'id="{bid}"')
            near = page[max(0, at - 200):at + 200]
            self.assertTrue("margin-left:auto" in near,
                            f"`{bid}` 가 만드는 단추 옆에 붙었다 (margin-left:auto 가 없다)")
        at = page.index('id="expDelUnpicked"')
        self.assertTrue('id="expStat"' in page[max(0, at - 320):at],
                        "`선별 외 삭제` 앞의 상태글(auto 여백)이 없어졌다")

    def test_ui_labels_are_korean_words_not_invented_abbreviations(self):
        """화면 라벨은 **읽어서 뜻이 통해야** 한다.

        `⇄찾바` 는 한국어 낱말이 아니라 뜻을 알 수 없었고(모달 제목은
        `찾아 바꾸기` 로 제대로 돼 있었다), `Highlight Emphasis` 는 전부 한국어인
        화면에 홀로 영어였다. 되돌아가지 않게 못박는다."""
        page = APP.render_page()
        # ⚠ `assertIn`/`assertNotIn` 은 실패하면 **페이지 300KB 를 통째로 덤프**해
        #   로그를 못 쓰게 만든다. 참/거짓으로 재고 짧은 말로 알린다.
        self.assertFalse("찾바" in page, "라벨이 `⇄찾바` 로 되돌아갔다 (낱말이 아니다)")
        self.assertTrue("⇄바꾸기" in page, "`⇄바꾸기` 라벨이 없다")
        self.assertFalse("Highlight Emphasis <span" in page,
                         "설정 라벨이 영어(`Highlight Emphasis`)로 되돌아갔다")
        self.assertTrue("가중치 색으로 보기" in page, "`가중치 색으로 보기` 라벨이 없다")

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

    def test_nai_renamed_tags_are_the_autocomplete_suggestions(self):
        data = {
            "rows": [
                ("v", 151368, "", "general", ["peace_sign", "v_sign"]),
                ("|_|", 21652, "", "general", ["||_||"]),
                ("tachi-e", 20834, "", "general", []),
            ]
        }
        with (
            patch.object(APP, "_ac_cache_load", return_value=None),
            patch.object(APP, "_ac_cache_save"),
        ):
            index = APP._ac_index_inner(data)
        with patch.object(APP, "_ac_index", return_value=index):
            self.assertEqual(
                APP.autocomplete_tags({}, "peace", 12)[0]["tag"],
                "peace sign",
            )
            self.assertEqual(
                APP.autocomplete_tags({}, "bar ey", 12)[0]["tag"],
                "bar eyes",
            )
            self.assertEqual(
                APP.autocomplete_tags({}, "tachi", 12)[0]["tag"],
                "character image",
            )

    def test_nai_renamed_tag_verification_never_needs_danbooru(self):
        old_tags = r"v, double v, |_|, \||/, :|, ;|, <|> <|>, eyepatch bikini, tachi-e"
        expected = {
            "peace sign", "double peace", "bar eyes", r"open \m/",
            "neutral face", "neco-arc eyes", "square bikini", "character image",
        }
        with (
            patch.dict(APP._TAGV_CACHE, {}, clear=True),
            patch.object(APP, "_tags_json", side_effect=AssertionError("network called")),
            patch.object(APP, "_tags_json_at", side_effect=AssertionError("network called")),
        ):
            result = APP.verify_tags(old_tags)
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["nai_renamed"], 9)
        self.assertTrue(all(x["status"] == "nai_renamed" for x in result["items"]))
        self.assertEqual({x["alias_to"] for x in result["items"]}, expected)

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
            APP.call_nai_api(
                "pst-fixture", "base", "", "", "negative", 832, 1216,
                seed=10,
                params={
                    **base,
                    "use_coords": True,
                    "_i2i": {"image": "fixture", "strength": 0.7, "noise": 0.0},
                },
                chars=people,
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
        self.assertEqual(
            [item["center"] for item in payloads[0]["parameters"]["characterPrompts"]],
            neutral,
        )
        self.assertEqual(centers(payloads[1], "v4_prompt"), chosen)
        self.assertEqual(centers(payloads[1], "v4_negative_prompt"), chosen)
        parameters = payloads[1]["parameters"]
        self.assertEqual(parameters["image_format"], "png")
        self.assertTrue(parameters["normalize_reference_strength_multiple"])
        self.assertEqual(
            parameters["characterPrompts"],
            [
                {"prompt": "A", "uc": "na", "center": chosen[0], "enabled": True},
                {"prompt": "B", "uc": "nb", "center": chosen[1], "enabled": True},
            ],
        )
        self.assertNotIn("extra_noise_seed", parameters)
        self.assertNotIn("color_correct", parameters)
        i2i_parameters = payloads[2]["parameters"]
        self.assertEqual(i2i_parameters["extra_noise_seed"], 9)
        self.assertFalse(i2i_parameters["color_correct"])

    def test_vibe_and_character_references_reach_actual_payload_in_aligned_arrays(self):
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

        params = {
            "model": "nai-diffusion-4-5-full",
            "_vibes": {
                "encoded": ["vibe-a", "vibe-b"],
                "strengths": [0.4, 0.9],
                "ies": [0.3, 0.8],
            },
            "_char_refs": {
                "images": ["char-a", "char-b"],
                "types": ["character", "character&style"],
                "strengths": [0.0, 2.0],
                "fidelities": [0.25, 1.0],
            },
        }
        with (
            patch.object(APP.requests, "post", side_effect=fake_post),
            self.assertLogs(APP.log, level="WARNING"),
        ):
            APP.call_nai_api(
                "pst-fixture", "base", "", "", "negative", 832, 1216,
                seed=1, params=params,
            )

        self.assertEqual(len(payloads), 1)
        sent = payloads[0]["parameters"]
        self.assertEqual(sent["reference_image_multiple"], ["vibe-a", "vibe-b"])
        self.assertEqual(sent["reference_strength_multiple"], [0.4, 0.9])
        self.assertEqual(
            sent["reference_information_extracted_multiple"], [0.3, 0.8]
        )
        self.assertTrue(sent["normalize_reference_strength_multiple"])
        self.assertEqual(sent["director_reference_images"], ["char-a", "char-b"])
        self.assertEqual(
            [
                item["caption"]["base_caption"]
                for item in sent["director_reference_descriptions"]
            ],
            ["character", "character&style"],
        )
        self.assertEqual(
            sent["director_reference_information_extracted"], [1.0, 1.0]
        )
        self.assertEqual(sent["director_reference_strength_values"], [0.0, 2.0])
        self.assertEqual(
            sent["director_reference_secondary_strength_values"], [0.75, 0.0]
        )
        for key in (
            "reference_image_multiple",
            "reference_strength_multiple",
            "reference_information_extracted_multiple",
            "director_reference_images",
            "director_reference_descriptions",
            "director_reference_information_extracted",
            "director_reference_strength_values",
            "director_reference_secondary_strength_values",
        ):
            self.assertEqual(len(sent[key]), 2, key)

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

    def test_legacy_middle_quality_suffix_is_removed_once(self):
        suffix = APP.quality_suffix_text("nai-diffusion-4-5-full")
        prompt = f"1girl, {suffix}, outdoors"
        cleaned, enabled = APP.split_quality_suffix(
            prompt, "nai-diffusion-4-5-full")
        self.assertTrue(enabled)
        self.assertEqual(cleaned, "1girl, outdoors")

        doubled = f"1girl, {suffix}, outdoors, {suffix}"
        cleaned, enabled = APP.split_quality_suffix(
            doubled, "nai-diffusion-4-5-full")
        self.assertTrue(enabled)
        self.assertEqual(cleaned, f"1girl, {suffix}, outdoors")

    def test_explicit_quality_toggle_state_wins_over_phrase_guessing(self):
        model = "nai-diffusion-4-5-full"
        suffix = APP.quality_suffix_text(model)
        prompt = f"1girl, {suffix}, outdoors"
        self.assertEqual(
            APP.restore_quality_prompt(prompt, model, {"quality_toggle": False}),
            (prompt, False),
        )
        self.assertEqual(
            APP.restore_quality_prompt(prompt, model, {"quality_toggle": True}),
            ("1girl, outdoors", True),
        )

    def test_metadata_import_preserves_explicit_quality_toggle_state(self):
        suffix = APP.quality_suffix_text("nai-diffusion-4-5-full")
        prompt = f"1girl, {suffix}, outdoors"
        for explicit, expected_base in (
            (False, prompt),
            (True, "1girl, outdoors"),
        ):
            metadata = PngInfo()
            metadata.add_text("Comment", json.dumps({
                "prompt": prompt,
                "uc": "bad anatomy",
                "source": "NovelAI Diffusion V4.5",
                "qualityToggle": explicit,
            }))
            source = io.BytesIO()
            Image.new("RGB", (2, 2), "white").save(
                source, "PNG", pnginfo=metadata)
            with tempfile.TemporaryDirectory() as td, patch.object(
                    APP, "IMG_CACHE", Path(td)):
                result = APP.ConfigServer(
                    copy.deepcopy(APP.DEFAULT_CONFIG)
                ).handle_inspect(source.getvalue(), "fixture.png", "")
            self.assertTrue(result["ok"])
            self.assertEqual(result["style"]["base"], expected_base)
            self.assertIs(
                result["style"]["params"]["quality_toggle"], explicit)
            self.assertNotIn(
                "quality_toggle_guessed", result["style"]["params"])

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

    def test_anlas_estimate_is_conservative_until_opus_tier_is_cached(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
        cfg["token"] = "pst-tier-fixture"
        cfg.update(width=832, height=1216, steps=28)
        server = APP.ConfigServer(cfg)
        with (
            patch.object(APP, "PREVIEW_PORT_RANGE", (port,)),
            patch.object(APP.webbrowser, "open", return_value=None),
        ):
            url = server.start()

        def post(data):
            request = urllib.request.Request(
                url + "api/anlas",
                data=json.dumps(data).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                return json.loads(response.read())

        try:
            unknown = post({"count": 1, "balance": False})
            self.assertFalse(unknown["est"]["free"])
            self.assertFalse(unknown["est"]["subscription_known"])
            self.assertIsNone(unknown["est"]["opus"])

            opus_balance = {
                "fixed": 1000,
                "purchased": 0,
                "total": 1000,
                "tier": 3,
                "opus": True,
                "active": True,
            }
            with patch.object(APP, "fetch_anlas_balance", return_value=opus_balance):
                fetched = post({"count": 1, "balance": True})
            self.assertTrue(fetched["est"]["free"])
            self.assertEqual(fetched["balance"], opus_balance)

            cached = post({"count": 1, "balance": False})
            self.assertTrue(cached["est"]["free"])
            self.assertTrue(cached["est"]["subscription_known"])
            self.assertTrue(cached["est"]["opus"])
            self.assertIsNone(cached["balance"])

            # 계정 토큰이 바뀌면 이전 계정의 Opus 상태를 상속하지 않는다.
            server.cfg["token"] = "pst-another-account"
            changed = post({"count": 1, "balance": False})
            self.assertFalse(changed["est"]["free"])
            self.assertFalse(changed["est"]["subscription_known"])
        finally:
            server.httpd.shutdown()
            server.httpd.server_close()

    def test_packs_imported_in_the_same_second_undo_independently(self):
        """한 번에 두 팩을 넣어도 판 id 가 겹치지 않고 **각각 따로** 되돌려진다.

        화면의 `sendPack` 은 고른 파일을 반복문으로 잇달아 넣는다. 판 id 가
        초 단위 시간뿐이면 두 팩이 **같은 초**에 들어가 id 가 겹쳤고, 그러면
        `undo_datapack` 이 먼저 들어온 판을 집어 **엉뚱한 자료를 지운 뒤**
        기록에서 겹친 판이 함께 빠져 나머지를 되돌릴 길이 사라졌다.
        되돌리기에는 휴지통이 없어 그 자료는 복구할 수 없었다."""
        def rows(prefix, n):
            return [{"id": f"{prefix}-{i}", "combo": f"artist:{prefix}{i}",
                     "artists": [f"{prefix}{i}"]} for i in range(n)]

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            with patch.object(APP, "BASE_DIR", base), \
                    patch.object(APP, "STYLE_FILE", base / "수집" / "그림체.json"), \
                    patch.object(APP, "IMG_CACHE", base / "수집" / "이미지캐시"):
                def styles():
                    return [x["id"] for x in json.loads(
                        APP.STYLE_FILE.read_text(encoding="utf-8"))]

                blob = lambda o: json.dumps(o, ensure_ascii=False).encode("utf-8")
                first = APP.import_datapack_bytes(blob(rows("first", 3)), "그림체.json")
                second = APP.import_datapack_bytes(blob(rows("second", 5)), "그림체.json")

                # 같은 초에 들어가도 id 가 겹치지 않는다 (이것이 회귀의 핵심이다).
                self.assertNotEqual(first["batch"], second["batch"])
                self.assertEqual(len(styles()), 8)
                self.assertEqual(len(APP.pack_log_brief()), 2)

                # 둘째 판만 되돌린다 — 첫째 판 자료는 온전해야 한다.
                undone = APP.undo_datapack(second["batch"])
                self.assertTrue(undone["ok"])
                self.assertEqual(styles(), [f"first-{i}" for i in range(3)])
                log_ids = [b["id"] for b in APP.pack_log_brief()]
                self.assertEqual(log_ids, [first["batch"]])

                # 남은 첫째 판도 여전히 되돌려진다 (기록이 함께 지워지지 않았다).
                self.assertTrue(APP.undo_datapack(first["batch"])["ok"])
                self.assertEqual(styles(), [])
                self.assertEqual(APP.pack_log_brief(), [])

    def test_legacy_pack_log_with_colliding_ids_still_undoes_one_batch_at_a_time(self):
        """id 가 이미 겹쳐 있는 **옛 기록**도 읽히고, 한 번에 한 판씩 되돌려진다.

        고치기 전에 만들어진 `가져온기록.json` 에는 겹친 id 가 남아 있을 수 있다.
        그때 id 로 기록을 걸러내면 손대지도 않은 판의 기록까지 사라졌다."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            with patch.object(APP, "BASE_DIR", base), \
                    patch.object(APP, "STYLE_FILE", base / "수집" / "그림체.json"), \
                    patch.object(APP, "IMG_CACHE", base / "수집" / "이미지캐시"):
                APP.STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
                APP.STYLE_FILE.write_text(json.dumps(
                    [{"id": "a-1"}, {"id": "b-1"}], ensure_ascii=False), encoding="utf-8")
                # 옛 판 id — 숫자만 있고 둘이 똑같다
                APP.save_pack_log([
                    {"id": "1785136158", "at": "옛날", "file": "가.json",
                     "lists": {"그림체.json": ["a-1"]}, "files": {}},
                    {"id": "1785136158", "at": "옛날", "file": "나.json",
                     "lists": {"그림체.json": ["b-1"]}, "files": {}},
                ])
                self.assertEqual(len(APP.pack_log_brief()), 2)

                self.assertTrue(APP.undo_datapack("1785136158")["ok"])
                left = json.loads(APP.STYLE_FILE.read_text(encoding="utf-8"))
                self.assertEqual([x["id"] for x in left], ["b-1"])
                # 나머지 한 판의 기록이 남아 있어야 그 자료도 되돌릴 수 있다
                self.assertEqual(len(APP.pack_log_brief()), 1)

                self.assertTrue(APP.undo_datapack("1785136158")["ok"])
                self.assertEqual(json.loads(
                    APP.STYLE_FILE.read_text(encoding="utf-8")), [])
                self.assertEqual(APP.pack_log_brief(), [])


if __name__ == "__main__":
    unittest.main()
