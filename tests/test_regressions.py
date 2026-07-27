"""No-cost deterministic regressions for the local NAI helper.

These tests never call NovelAI. They cover failures found during the 2026-07
audit and are intentionally runnable with the Python standard test runner.
"""

from __future__ import annotations

import copy
import hashlib
import io
import importlib.util
import json
import socket
import tempfile
import threading
import time
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
BUILD_SPEC = importlib.util.spec_from_file_location("nai_build_under_test", ROOT / "빌드.py")
assert BUILD_SPEC and BUILD_SPEC.loader
BUILD = importlib.util.module_from_spec(BUILD_SPEC)
BUILD_SPEC.loader.exec_module(BUILD)


class RegressionTests(unittest.TestCase):
    def test_over_limit_prompts_are_preserved_in_actual_payload(self):
        base = ", ".join(f"base_tag_{i}" for i in range(900))
        char = ", ".join(f"character_tag_{i}" for i in range(500))
        negative = ", ".join(f"negative_tag_{i}" for i in range(900))
        char_negative = ", ".join(f"character_negative_{i}" for i in range(500))
        self.assertGreater(APP.nai_tokens(base) + APP.nai_tokens(char), 512)
        self.assertGreater(
            APP.nai_tokens(negative) + APP.nai_tokens(char_negative), 512)

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

        with patch.object(APP.requests, "post", side_effect=fake_post):
            APP.call_nai_api(
                "pst-fixture", base, "", "", negative, 832, 1216,
                seed=1,
                params={"model": "nai-diffusion-4-5-full", "uc_preset": 4},
                chars=[{"prompt": char, "negative": char_negative}],
            )

        params = payloads[0]["parameters"]
        self.assertEqual(payloads[0]["input"], base)
        self.assertEqual(
            params["v4_prompt"]["caption"]["base_caption"], base)
        self.assertEqual(
            params["v4_prompt"]["caption"]["char_captions"][0]["char_caption"],
            char,
        )
        self.assertEqual(
            params["v4_negative_prompt"]["caption"]["base_caption"], negative)
        self.assertEqual(
            params["v4_negative_prompt"]["caption"]["char_captions"][0]["char_caption"],
            char_negative,
        )
        self.assertIn("⚠ 입력은 보존", APP.PAGE_TEMPLATE)
        self.assertNotIn("뒷부분이 잘립니다", APP.PAGE_TEMPLATE)

    def test_weight_highlight_does_not_draw_text_twice(self):
        page = APP.PAGE_TEMPLATE
        self.assertIn(
            ".hlwrap .hl *{color:transparent!important;"
            "-webkit-text-fill-color:transparent!important;", page)
        self.assertIn(".hl b{font-weight:400;border-radius:3px;padding:0;}", page)
        self.assertNotIn(
            ".hl .w-num{color:var(--accent);opacity:.95;}", page)
        self.assertNotIn(".hl b{font-weight:400;border-radius:3px;padding:0 1px;}", page)
        self.assertIn(
            ".hlwrap .hl{position:absolute;top:0;left:0;", page)
        self.assertIn(
            "padding:8px 10px;border:1px solid transparent;", page)
        self.assertIn("layer.style.width = (ta.clientWidth + 2) + 'px';", page)
        self.assertIn("layer.style.height = (ta.clientHeight + 2) + 'px';", page)
        self.assertIn(
            "function hlOn(){ return (STATE.ui || {}).highlight === true; }",
            page,
        )
        self.assertIn(
            '<select id="uiHighlight"><option value="off">끔 (선명한 원문)</option>',
            page,
        )

    def test_builder_routes_character_variants_and_negative_separately(self):
        """캐릭터 외형을 바꾸는 후보는 베이스에, 네거티브 후보는 양성에 섞지 않는다."""
        builder = APP.load_builder()
        char_names = [step.get("이름") for step in builder["캐릭터단계"]]
        base_names = [step.get("이름") for step in builder["베이스단계"]]
        self.assertIn("예술적 변형 (원작과 다르게)", char_names)
        self.assertNotIn("예술적 변형 (원작과 다르게)", base_names)
        negative_steps = [
            step for step in builder["베이스단계"]
            if step.get("이름") == "네거티브"
        ]
        self.assertEqual(len(negative_steps), 1)
        self.assertEqual(negative_steps[0].get("출력"), "negative")
        combo_slots = [
            slot
            for step in builder["베이스단계"]
            for slot in (step.get("슬롯") or [])
            if slot.get("라벨") == "작가 조합"
        ]
        self.assertEqual(len(combo_slots), 1)
        self.assertTrue(combo_slots[0].get("조합전용"))

        page = APP.PAGE_TEMPLATE
        self.assertIn('data-output="${output}"', page)
        self.assertIn("composeSelected('positive')", page)
        self.assertIn("composeSelected('negative')", page)
        self.assertIn("negative:c.negative || negative", page)
        self.assertIn('id="bldUseNow" checked', page)
        self.assertIn("const hydrateSection = sec =>", page)
        self.assertIn("select._bldCandidates =", page)
        self.assertIn("if(body.classList.contains('hidden')) hydrateSection", page)

    def test_completed_settings_migration_drops_retired_partner_keys(self):
        """이전이 끝난 male_prompt가 화면 저장 때마다 잘못된 키 경고를 만들면 안 된다."""
        cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
        cfg.update({
            "_settings_migrated": True,
            "male_prompt": "",
            "male_outfit": "",
        })
        APP.migrate_legacy_selections(cfg)
        self.assertNotIn("male_prompt", cfg)
        self.assertNotIn("male_outfit", cfg)

    def test_builder_saves_style_settings_and_character_negative(self):
        """빌더 저장도 빠른 프리셋 저장과 같은 묶음 규칙을 지킨다."""
        page = APP.PAGE_TEMPLATE
        builder_save = page[page.index("if(m === 'style' || m === 'char')"):]
        self.assertIn("negative, settings:styleSettingsFromUI()", builder_save)
        self.assertIn("function styleSettingsFromUI()", page)
        for field in (
            "quality_toggle", "smea", "smea_dyn", "dynamic_thresholding",
            "uncond_scale", "controlnet_strength", "prefer_brownian",
            "deliberate_euler_ancestral_bug",
        ):
            self.assertIn(f"{field}:", page)
        self.assertIn("JSON.stringify({type:'char', name, negative,", builder_save)
        self.assertIn("groups:{'조합': composed}", builder_save)
        self.assertIn("const lb = f.querySelector('.slot-name')", builder_save)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
            cfg["characters"] = []
            with (
                patch.object(APP, "CHAR_DIR", root / "캐릭터"),
                patch.object(APP, "SETTINGS_FILE", root / "설정.json"),
            ):
                result = APP.ConfigServer(cfg).handle_norm_save(json.dumps({
                    "type": "char",
                    "name": "검증 캐릭터",
                    "negative": "character-specific negative",
                    "groups": {"조합": "1girl, alternate costume"},
                    "builder_groups": {
                        "인물·성별·인원": "1girl",
                        "예술적 변형·의상 변경": "alternate costume",
                    },
                }, ensure_ascii=False))
            self.assertTrue(result["ok"])
            made = result["characters"][-1]
            self.assertEqual(made["female"], "1girl, alternate costume")
            self.assertEqual(made["negative"], "character-specific negative")
            self.assertEqual(
                made["groups"]["예술적 변형·의상 변경"], "alternate costume")

    def test_style_file_round_trip_preserves_extended_generation_settings(self):
        settings = {
            "model": "nai-diffusion-4-5-full",
            "cfg_scale": 6.2, "cfg_rescale": 0.31, "steps": 31,
            "sampler": "k_dpmpp_2m", "scheduler": "karras",
            "variety": True, "width": 1024, "height": 1024,
            "uc_preset": 1, "quality_toggle": False,
            "smea": True, "smea_dyn": True, "dynamic_thresholding": True,
            "uncond_scale": 0.42, "controlnet_strength": 1.4,
            "prefer_brownian": False, "deliberate_euler_ancestral_bug": True,
            "legacy_v3_extend": True,
        }
        with tempfile.TemporaryDirectory() as td, patch.object(
                APP, "STYLE_DIR", Path(td) / "그림체"):
            APP.save_style_file(
                "묶음", prompt="whole positive", negative="", settings=settings)
            loaded = APP.list_styles({"그림체_그룹": []})[0]
        self.assertEqual(loaded["prompt"], "whole positive")
        self.assertEqual(loaded["negative"], "")
        self.assertEqual(loaded["settings"], settings)

    def test_style_and_setting_files_recover_from_last_backup(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            style_file = root / "수집" / "그림체.json"
            combo_file = root / "수집" / "작가조합.json"
            settings_dir = root / "세팅"
            old_cache = copy.deepcopy(APP._COMBOS)
            try:
                with (
                    patch.object(APP, "STYLE_FILE", style_file),
                    patch.object(APP, "COMBO_FILE", combo_file),
                    patch.object(APP, "SETTINGS_DIR", settings_dir),
                ):
                    APP._COMBOS.update({"loaded": False, "rows": []})
                    APP.add_style({
                        "id": "first", "artists": ["first"], "params": {"seed": 1}})
                    APP.add_style({
                        "id": "second", "artists": ["second"], "params": {"seed": 2}})
                    style_file.write_text("{broken", encoding="utf-8")
                    APP._COMBOS.update({"loaded": False, "rows": []})
                    recovered = APP.load_combos()
                    self.assertEqual([x["id"] for x in recovered], ["first"])
                    self.assertEqual(
                        json.loads(style_file.read_text(encoding="utf-8"))[0]["id"],
                        "first",
                    )

                    made = APP.new_setting("안전", mode="단독")
                    self.assertTrue(made["ok"])
                    self.assertTrue(
                        APP.setting_add_set("안전", "시험 세트")["ok"])
                    APP.setting_meta_save("안전", {"방식": "남녀"})
                    setting = settings_dir / "안전.json"
                    setting.write_text("{broken", encoding="utf-8")
                    listed = APP.list_settings()
                    self.assertEqual(len(listed), 1)
                    self.assertEqual(listed[0]["name"], "안전")
                    removed = APP.setting_delete("안전")
                    self.assertTrue(removed["ok"])
                    self.assertFalse(setting.exists())
                    self.assertTrue((settings_dir / removed["backup"]).exists())
            finally:
                APP._COMBOS.clear()
                APP._COMBOS.update(old_cache)

    def test_concurrent_setting_edits_are_one_read_modify_write_transaction(self):
        """서로 다른 정상 저장 두 개가 겹쳐도 마지막 요청이 앞 변경을 지우면 안 된다."""
        with tempfile.TemporaryDirectory() as td:
            settings_dir = Path(td) / "세팅"
            with patch.object(APP, "SETTINGS_DIR", settings_dir):
                self.assertTrue(APP.new_setting("동시저장", mode="단독")["ok"])
                real_load = APP.load_json_recover
                activity = {"now": 0, "max": 0}
                activity_lock = threading.Lock()

                def slow_load(path):
                    with activity_lock:
                        activity["now"] += 1
                        activity["max"] = max(activity["max"], activity["now"])
                    try:
                        time.sleep(0.05)
                        return real_load(path)
                    finally:
                        with activity_lock:
                            activity["now"] -= 1

                results = []
                with patch.object(APP, "load_json_recover", side_effect=slow_load):
                    workers = [
                        threading.Thread(target=lambda: results.append(
                            APP.setting_meta_save("동시저장", {"방식": "남녀"}))),
                        threading.Thread(target=lambda: results.append(
                            APP.setting_meta_save("동시저장", {"단계명": ["도입", "완료"]}))),
                    ]
                    for worker in workers:
                        worker.start()
                    for worker in workers:
                        worker.join()

                saved = APP.load_json_recover(settings_dir / "동시저장.json")
                self.assertEqual(activity["max"], 1)
                self.assertEqual(len(results), 2)
                self.assertTrue(all(x["ok"] for x in results))
                self.assertEqual(saved["방식"], "남녀")
                self.assertEqual(saved["단계명"], ["도입", "완료"])

    def test_generated_image_is_published_only_after_complete_encoding(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "result.png"
            image = Image.new("RGB", (8, 8), "white")
            image.nai_comment = json.dumps({"prompt": "whole"}, ensure_ascii=False)
            saved = APP.save_with_meta(image, target, fmt="png")
            self.assertEqual(saved, target)
            with Image.open(saved) as check:
                check.load()
                self.assertEqual(check.size, (8, 8))
            self.assertFalse(list(Path(td).glob(".*.tmp")))

    def test_combo_cards_do_not_duplicate_full_records_into_html_attributes(self):
        page = APP.PAGE_TEMPLATE
        self.assertIn("el._comboRecord = c", page)
        self.assertNotIn('data-cfull="${escA(JSON.stringify(c))}"', page)
        self.assertNotIn('data-csave="${escA(JSON.stringify(c))}"', page)
        self.assertNotIn('data-crate="${escA(JSON.stringify(c.artists||[]))}"', page)
        self.assertIn("const fragment = document.createDocumentFragment()", page)
        self.assertIn('<option selected>20</option><option>50</option>', page)
        self.assertIn('className = \'row combo-card\'', page)
        self.assertIn('loading="lazy" decoding="async" fetchpriority="low"', page)
        self.assertIn("content-visibility:auto", page)

    def test_combo_list_payload_omits_heavy_fields_unused_by_cards(self):
        """목록에서 캐릭터 원문까지 보내 멈추지 말되 그림체 묶음 적용값은 보존한다."""
        row = {
            "id": "style-1", "title": "Style", "combo": "artist:a",
            "artists": ["a"], "base": "whole base", "negative": "whole negative",
            "params": {"scale": 5.5}, "images": ["first.webp", "second.webp"],
            "characters": [{"prompt": "x" * 10000}],
            "rest": "y" * 10000, "weights": {"a": 1.0},
        }
        with (
            patch.object(APP, "load_combos", return_value=[row]),
            patch.object(APP, "style_rating", return_value={
                "score": 0, "fav": False, "block": False, "rated": 0,
            }),
        ):
            item = APP.search_combos(limit=20)["items"][0]
        self.assertEqual(item["base"], "whole base")
        self.assertEqual(item["negative"], "whole negative")
        self.assertEqual(item["params"], {"scale": 5.5})
        self.assertEqual(item["images"], ["first.webp"])
        for unused in ("characters", "rest", "weights"):
            self.assertNotIn(unused, item)

    def test_combo_search_loads_artist_ratings_once_per_request(self):
        rows = [
            {"id": f"s{i}", "combo": f"artist:a{i}", "artists": [f"a{i}"]}
            for i in range(200)
        ]
        calls = []

        def ratings():
            calls.append(1)
            return {}

        with (
            patch.object(APP, "load_combos", return_value=rows),
            patch.object(APP, "load_ratings", side_effect=ratings),
        ):
            result = APP.search_combos(limit=200)
        self.assertEqual(len(result["items"]), 200)
        self.assertEqual(len(calls), 1)

    def test_builder_combo_picker_preserves_builder_and_recipes_load_lazily(self):
        page = APP.PAGE_TEMPLATE
        paint = page[page.index("function paint(){"):
                     page.index("/* ── 자료 비교 생성")]
        self.assertNotIn("loadRecipes(false)", paint)
        self.assertIn("new IntersectionObserver", page)
        self.assertIn("RECIPES_OBSERVER.observe(target)", page)
        self.assertIn("while($('modalBody').firstChild) saved.appendChild", page)
        self.assertIn("$('modalBody').replaceChildren(back.body)", page)
        self.assertIn("returnToBuilder(val)", page)
        self.assertIn("작가 조합을 넣고 빌더로 돌아왔습니다", page)
        self.assertIn("const name = $('bldName'); if(name) name.focus()", page)
        self.assertIn("WELCOME_COUNT_TIMER = setTimeout", page)
        self.assertIn("clearTimeout(WELCOME_COUNT_TIMER)", page)

    def test_concurrent_combo_requests_parse_the_collection_once(self):
        """첫 화면 개수 조회와 모달 열기가 겹쳐도 큰 JSON을 중복 파싱하지 않는다."""
        old_cache = copy.deepcopy(APP._COMBOS)
        calls, results = [], []
        try:
            with tempfile.TemporaryDirectory() as td:
                style_file = Path(td) / "그림체.json"
                style_file.write_text("[]", encoding="utf-8")

                def slow_load(_path):
                    calls.append(1)
                    time.sleep(0.08)
                    return [{"id": "only", "combo": "artist:a"}]

                APP._COMBOS.update({"loaded": False, "rows": []})
                with (
                    patch.object(APP, "STYLE_FILE", style_file),
                    patch.object(APP, "COMBO_FILE", Path(td) / "없음.json"),
                    patch.object(APP, "load_json_recover", side_effect=slow_load),
                ):
                    workers = [
                        threading.Thread(target=lambda: results.append(APP.load_combos()))
                        for _ in range(4)
                    ]
                    for worker in workers:
                        worker.start()
                    for worker in workers:
                        worker.join()
        finally:
            APP._COMBOS.clear()
            APP._COMBOS.update(old_cache)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(results), 4)
        self.assertTrue(all(rows[0]["id"] == "only" for rows in results))

    def test_distribution_separates_program_from_all_content_data(self):
        self.assertIn("t5_tokenizer.json", BUILD.ASSETS)
        for content in (
            "후보사전.json", "규격.json", "옵션.json",
            "asset_config.json", "설정.txt",
        ):
            self.assertNotIn(content, BUILD.ASSETS)
        for content_dir in ("태그", "캐릭터", "세팅", "tests",
                            "수집", "output", "프로필"):
            self.assertNotIn(content_dir, BUILD.ASSET_DIRS)
        # UI 코드는 개인 자료가 아니라 프로그램 자산이다. 새 화면 CSS를 start.py에
        # 다시 쌓지 않고 exe 옆에 함께 둔다.
        self.assertEqual(BUILD.ASSET_DIRS, ["ui"])
        self.assertEqual(
            set(BUILD.DATA_PACK_ASSETS),
            {"후보사전.json", "규격.json", "옵션.json"},
        )
        self.assertEqual(set(BUILD.DATA_PACK_DIRS), {"태그", "세팅"})

        with tempfile.TemporaryDirectory() as td:
            pack = BUILD.build_data_pack(Path(td))
            with zipfile.ZipFile(pack) as archive:
                names = set(archive.namelist())
        self.assertIn("후보사전.json", names)
        self.assertIn("규격.json", names)
        self.assertIn("옵션.json", names)
        self.assertTrue(any(x.startswith("태그/") for x in names))
        self.assertTrue(any(x.startswith("세팅/") for x in names))
        self.assertNotIn("asset_config.json", names)
        self.assertFalse(any(x.startswith("수집/") for x in names))

    def test_comparison_plan_counts_each_mode_and_preserves_style_bundle(self):
        cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
        cfg["char_slots"] = [{"name": "현재", "prompt": "current character"}]
        cfg["characters"] = [
            {"id": "a", "name": "A", "female": "character a",
             "clothed": "red dress", "negative": "neg a"},
            {"id": "b", "name": "B", "female": "character b", "negative": "neg b"},
        ]
        styles = [
            {"id": "s1", "title": "S1", "base": "style one",
             "negative": "style neg one",
             "params": {"scale": 7.0, "steps": 31, "width": 1024, "height": 1024}},
            {"id": "s2", "title": "S2", "base": "style two",
             "negative": "style neg two",
             "params": {"scale": 4.0, "steps": 20, "width": 832, "height": 1216}},
        ]
        with (
            patch.object(APP, "load_combos", return_value=styles),
            patch.object(APP, "list_styles", return_value=[]),
        ):
            style_plan = APP.comparison_plan(
                cfg, {"mode": "styles", "width": 640, "height": 960})
            char_plan = APP.comparison_plan(
                cfg, {"mode": "characters", "width": 640, "height": 960})
            both_plan = APP.comparison_plan(
                cfg, {"mode": "both", "width": 640, "height": 960, "limit": 3})
            multi_seed_plan = APP.comparison_plan(
                cfg, {
                    "mode": "both", "width": 640, "height": 960,
                    "seed_count": 3,
                },
            )
            source_styles, source_chars = APP.comparison_sources(cfg)

        self.assertEqual(style_plan["count"], 2)
        self.assertEqual(style_plan["current_slots"], 1)
        self.assertEqual(char_plan["count"], 2)
        self.assertEqual(both_plan["total"], 4)
        self.assertEqual(both_plan["count"], 3)
        self.assertTrue(both_plan["limited"])
        self.assertEqual(multi_seed_plan["combinations"], 4)
        self.assertEqual(multi_seed_plan["seed_count"], 3)
        self.assertEqual(multi_seed_plan["total"], 12)
        multi_seed_jobs = list(APP.iter_comparison_jobs(
            cfg, multi_seed_plan, source_styles, source_chars))
        self.assertEqual(len(multi_seed_jobs), 12)
        self.assertEqual(
            [job["seed_index"] for job in multi_seed_jobs[:3]],
            [0, 1, 2],
        )
        self.assertEqual(len({job["key"] for job in multi_seed_jobs}), 12)

        first_job = next(APP.iter_comparison_jobs(
            cfg, both_plan, source_styles, source_chars))
        used, base, negative, people, _ = APP.comparison_job_values(
            cfg, both_plan, first_job)
        self.assertEqual(base, "style one")
        self.assertEqual(negative, "style neg one")
        self.assertEqual(used["cfg_scale"], 7.0)
        self.assertEqual(used["steps"], 31)
        self.assertEqual((used["width"], used["height"]), (640, 960))
        self.assertEqual(people[0]["prompt"], "character a, red dress")
        self.assertEqual(people[0]["negative"], "neg a")
        original_signature = APP.comparison_signature(
            cfg, both_plan, source_styles, source_chars)
        changed_chars = copy.deepcopy(source_chars)
        changed_chars[0]["clothed"] = "blue dress"
        self.assertNotEqual(
            original_signature,
            APP.comparison_signature(cfg, both_plan, source_styles, changed_chars),
            "착의가 달라진 비교 계획을 이전 진행 기록으로 오인하면 안 된다")

        no_lock = APP.comparison_style_config(
            cfg, source_styles[0],
            APP.normalize_comparison_options(
                {"mode": "styles", "fixed_size": False}, cfg))
        self.assertEqual((no_lock["width"], no_lock["height"]), (1024, 1024))

    def test_comparison_keeps_coordinates_aligned_after_disabled_character(self):
        cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
        cfg["char_slots"] = [
            {"name": "off", "prompt": "off character", "enabled": False},
            {"name": "on", "prompt": "on character", "enabled": True},
        ]
        cfg["char_centers"] = [
            {"x": 0.1, "y": 0.2},
            {"x": 0.8, "y": 0.9},
        ]
        plan = {"options": APP.normalize_comparison_options(
            {"mode": "styles"}, cfg)}
        job = {
            "style": {
                "_compare_id": "style", "_compare_name": "Style",
                "base": "style base", "negative": "",
            },
            "character": None,
        }

        _, _, _, people, centers = APP.comparison_job_values(
            cfg, plan, job)

        self.assertEqual(people, [{"prompt": "on character", "negative": ""}])
        self.assertEqual(centers, [{"x": 0.8, "y": 0.9}])

    def test_comparison_requires_the_exact_recounted_job_confirmation(self):
        cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
        cfg["token"] = "pst-fixture"
        cfg["characters"] = [{"id": "a", "name": "A", "female": "character a"}]
        server = APP.ConfigServer(cfg)
        with (
            patch.object(APP, "load_combos", return_value=[]),
            patch.object(APP, "list_styles", return_value=[]),
        ):
            rejected = server.handle_compare_run(json.dumps({
                "mode": "characters", "confirmed": True, "confirmed_count": 2,
            }).encode("utf-8"))
        self.assertFalse(rejected["ok"])
        self.assertIn("1장", rejected["error"])
        self.assertFalse(server.live.running)

    def test_comparison_worker_saves_then_resumes_without_paid_network(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
            cfg.update(
                token="pst-fixture",
                out_dir=str(root / "output"),
                characters=[
                    {"id": "a", "name": "A", "female": "character a",
                     "clothed": "red dress",
                     "negative": "neg a"},
                    {"id": "b", "name": "B", "female": "character b",
                     "negative": "neg b"},
                ],
                pace={"delay_min": 0, "delay_max": 0, "daily_cap": 100},
            )
            styles = [{
                "id": "s1", "_compare_id": "s1", "_compare_name": "Style",
                "base": "style base", "negative": "style negative",
                "params": {"scale": 6.5, "steps": 24, "width": 1024, "height": 1024},
            }]
            chars = APP.comparison_characters(cfg)
            plan = APP.comparison_plan(
                cfg, {"mode": "both", "fixed_size": True,
                      "width": 512, "height": 512, "same_seed": True,
                      "seed_count": 2},
                opus=True)
            # comparison_plan reads global sources; replace its counts with the fixture's exact plan.
            plan.update(ok=True, errors=[], styles=1, characters=2,
                        combinations=2, seed_count=2,
                        total=4, count=4, limited=False,
                        mode_label=APP.COMPARE_MODE_LABELS["both"])
            state = {"seeds": {}, "progress": {}, "daily": {}, "total_generated": 0}
            server = APP.ConfigServer(cfg)
            calls = []

            def fake_generate(_token, base, _female, _male, negative, width, height, **kw):
                calls.append({
                    "base": base, "negative": negative,
                    "width": width, "height": height,
                    "chars": kw["chars"], "seed": kw["seed"],
                    "scale": kw["scale"],
                })
                image = Image.new("RGB", (width, height), "white")
                image.nai_seed = kw["seed"]
                if len(calls) == 1:
                    server.live.stop_req = True
                return image

            progress_file = root / "비교생성-진행.json"
            with (
                patch.object(APP, "COMPARE_PROGRESS_FILE", progress_file),
                patch.object(APP, "load_state", return_value=state),
                patch.object(APP, "save_state", return_value=None),
                patch.object(APP, "pace_gate", return_value=(True, "")),
                patch.object(APP, "pace_complete", return_value=None),
                patch.object(APP, "call_nai_api", side_effect=fake_generate),
            ):
                APP._run_comparison(server, cfg, plan, styles, chars)
                first = json.loads(progress_file.read_text(encoding="utf-8"))
                self.assertEqual(first["status"], "stopped")
                self.assertEqual(len(first["completed"]), 1)

                server.live.stop_req = False
                APP._run_comparison(server, cfg, plan, styles, chars)
                final = json.loads(progress_file.read_text(encoding="utf-8"))
                first_record = min(
                    final["completed"].values(),
                    key=lambda item: item["index"],
                )
                restored = APP.comparison_recipe_for_output(
                    cfg, first_record["file"])

            self.assertEqual(len(calls), 4)
            self.assertEqual(final["status"], "complete")
            self.assertEqual(len(final["completed"]), 4)
            self.assertEqual(calls[0]["seed"], calls[2]["seed"])
            self.assertEqual(calls[1]["seed"], calls[3]["seed"])
            self.assertNotEqual(calls[0]["seed"], calls[1]["seed"])
            self.assertEqual(
                {(x["width"], x["height"]) for x in calls}, {(512, 512)})
            self.assertEqual(
                [x["chars"][0]["prompt"] for x in calls],
                ["character a, red dress", "character a, red dress",
                 "character b", "character b"])
            self.assertTrue(all(x["base"] == "style base" for x in calls))
            self.assertTrue(all(x["negative"] == "style negative" for x in calls))
            self.assertTrue(all(x["scale"] == 6.5 for x in calls))
            self.assertEqual(len(list((root / "output").rglob("*.webp"))), 4)
            self.assertEqual(len(list((root / "output").rglob("manifest.json"))), 1)
            recipe = restored["recipe"]
            self.assertEqual(recipe["base_prompt"], "style base")
            self.assertEqual(recipe["negative_prompt"], "style negative")
            self.assertEqual(recipe["settings"]["cfg_scale"], 6.5)
            self.assertEqual(
                (recipe["settings"]["width"], recipe["settings"]["height"]),
                (512, 512),
            )
            self.assertEqual(recipe["char_slots"][0]["prompt"], "character a")
            self.assertEqual(recipe["char_slots"][0]["outfit"], "red dress")
            self.assertEqual(recipe["nai_seed"], calls[0]["seed"])
            self.assertEqual(
                recipe["source"]["style"]["id"], "s1")
            live = server.live.snapshot()
            self.assertEqual(live["phase"], "completed")
            self.assertEqual((live["completed"], live["failed"]), (4, 0))

    def test_comparison_ui_keeps_the_three_choices_and_explicit_acknowledgement(self):
        page = APP.render_page()
        for value in ("styles", "characters", "both"):
            self.assertIn(f'name="cmpMode" value="{value}"', page)
        self.assertIn('id="cmpFix" checked', page)
        self.assertIn("#cmpCustom.hidden{display:none;}", page)
        self.assertIn('id="cmpSameSeed" checked', page)
        self.assertIn('id="cmpSeedCount"', page)
        self.assertIn("seed_count: Math.max(1, Math.min(4,", page)
        self.assertIn("× 시드 ${Number(r.seed_count).toLocaleString()}개", page)
        self.assertIn('id="cmpConfirm"', page)
        self.assertIn("confirmed_count:CMP_PLAN.count", page)
        self.assertIn("중지하거나 일일 상한에 닿아도 같은 계획으로 다시 누르면 이어집니다.", page)
        self.assertIn('id="cmpOpenResults"', page)
        self.assertIn('id="cmpRuns"', page)
        self.assertIn('id="cmpRunLoad"', page)
        self.assertIn('id="cmpRunOpen"', page)
        self.assertIn("fetch('/api/compare_runs')", page)
        self.assertIn("fetch('/api/compare_activate'", page)
        self.assertIn("await openComparisonFolder(", page)
        self.assertIn('id="expApplyPicked"', page)
        self.assertIn("fetch('/api/compare_recipe'", page)
        self.assertIn("fetch('/api/compare_promote'", page)
        self.assertIn("그림체 묶음으로 저장", page)
        self.assertIn("캐릭터를 각각 저장", page)
        self.assertIn("세팅은 이 비교에 포함되지 않아", page)
        self.assertIn("EXP_RECIPE_UNDO", page)
        self.assertIn("적용 전으로 되돌리기", page)

    def test_shared_live_state_tracks_owner_stop_retry_and_outcome(self):
        live = APP.LiveState()
        token = live.try_claim("자료 비교 생성", "library")
        self.assertIsNotNone(token)
        self.assertIsNone(live.try_claim("겹친 생성", "preview"))
        running = live.snapshot()
        self.assertTrue(running["running"])
        self.assertEqual(running["operation"], "자료 비교 생성")
        self.assertEqual(running["phase"], "running")
        self.assertEqual(running["retry_mode"], "library")

        live.note_retry("HTTP 500")
        live.update(
            completed=2, failed=1, phase="partial",
            last_error="한 장 실패", can_retry=True)
        live.release(token)
        partial = live.snapshot()
        self.assertFalse(partial["running"])
        self.assertEqual(partial["phase"], "partial")
        self.assertEqual(partial["retry_count"], 1)
        self.assertEqual((partial["completed"], partial["failed"]), (2, 1))
        self.assertTrue(partial["can_retry"])

        second = live.try_claim("씬 모드", "settings")
        self.assertTrue(live.request_stop())
        self.assertEqual(live.snapshot()["phase"], "stopping")
        live.release(second)
        stopped = live.snapshot()
        self.assertEqual(stopped["phase"], "stopped")
        self.assertTrue(stopped["can_retry"])

    def test_single_generation_failure_is_visible_without_paid_network(self):
        cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
        cfg["token"] = "pst-fixture"
        server = APP.ConfigServer(cfg)
        with (
            patch.object(APP, "pace_gate", return_value=(True, "")),
            patch.object(APP, "pace_complete", return_value=None),
            patch.object(APP, "load_state", return_value={
                "seeds": {}, "progress": {}, "daily": {},
                "total_generated": 0,
            }),
            patch.object(
                APP, "call_nai_api",
                side_effect=APP.APIError("fixture failure")),
        ):
            result = server.handle_generate_one()
            deadline = time.time() + 2
            while server.live.running and time.time() < deadline:
                time.sleep(0.01)

        self.assertTrue(result["ok"])
        status = server.live.snapshot()
        self.assertFalse(status["running"])
        self.assertEqual(status["operation"], "단독 생성")
        self.assertEqual(status["phase"], "failed")
        self.assertEqual(status["failed"], 1)
        self.assertTrue(status["can_retry"])
        self.assertIn("fixture failure", status["last_error"])

    def test_preview_exposes_operation_phase_status_and_retry_navigation(self):
        page = APP.render_page()
        for element_id in ("pvPhase", "pvStatus", "pvCounts", "pvReturn"):
            self.assertIn(f'id="{element_id}"', page)
        self.assertIn("LIVE_PHASE_LABEL", page)
        self.assertIn("s.operation || s.char_name", page)
        self.assertIn("s.status_text || '-'", page)
        self.assertIn("자동 재시도 ${s.retry_count}", page)
        self.assertIn("!s.can_retry || !!s.running", page)

    def test_comparison_recipe_promotion_preserves_bundles_and_skips_duplicates(self):
        recipe = {
            "base_prompt": "style base\n1.2::detail::",
            "negative_prompt": "style negative",
            "style_name": "승자",
            "settings": {
                "model": "nai-diffusion-4-5-full",
                "width": 512, "height": 512,
                "cfg_scale": 6.5, "steps": 28,
            },
            "char_slots": [
                {"name": "기존", "prompt": "char a", "outfit": "red dress",
                 "negative": "bad hands", "enabled": True},
                {"name": "신규", "prompt": "char b", "outfit": "blue dress",
                 "negative": "bad feet", "enabled": True},
            ],
        }
        restored = {
            "ok": True, "file": "비교생성/run/winner.webp",
            "recipe": recipe,
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            style_dir = root / "그림체"
            char_dir = root / "캐릭터"
            settings_file = root / "설정.json"
            cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
            cfg["characters"] = [{
                "id": "existing", "name": "기존 저장본",
                "female": "char a", "clothed": "red dress",
                "negative": "bad hands", "enabled": True,
            }]
            with (
                patch.object(APP, "STYLE_DIR", style_dir),
                patch.object(APP, "CHAR_DIR", char_dir),
                patch.object(APP, "SETTINGS_FILE", settings_file),
                patch.object(
                    APP, "comparison_recipe_for_output",
                    return_value=restored),
            ):
                style_first = APP.promote_comparison_recipe_assets(
                    cfg, "ignored.webp", "style", name="승자",
                    spec={"그림체_그룹": []})
                style_again = APP.promote_comparison_recipe_assets(
                    cfg, "ignored.webp", "style", name="다른 이름",
                    spec={"그림체_그룹": []})
                chars = APP.promote_comparison_recipe_assets(
                    cfg, "ignored.webp", "characters",
                    spec={"그림체_그룹": []})
                setting = APP.promote_comparison_recipe_assets(
                    cfg, "ignored.webp", "setting",
                    spec={"그림체_그룹": []})

            saved_style = json.loads(
                (style_dir / "승자.json").read_text(encoding="utf-8"))
            self.assertEqual(saved_style["프롬프트"], recipe["base_prompt"])
            self.assertEqual(saved_style["네거티브"], recipe["negative_prompt"])
            self.assertEqual(saved_style["설정"], recipe["settings"])
            self.assertEqual((style_first["saved"], style_first["existing"]), (1, 0))
            self.assertEqual((style_again["saved"], style_again["existing"]), (0, 1))
            self.assertEqual(len(list(style_dir.glob("*.json"))), 1)
            self.assertEqual((chars["saved"], chars["existing"]), (1, 1))
            self.assertEqual(len(cfg["characters"]), 2)
            self.assertEqual(cfg["characters"][1]["female"], "char b")
            self.assertEqual(cfg["characters"][1]["clothed"], "blue dress")
            self.assertEqual(cfg["characters"][1]["negative"], "bad feet")
            self.assertEqual(len(list(char_dir.glob("*.json"))), 2)
            self.assertTrue(settings_file.is_file())
            self.assertFalse(setting["ok"])
            self.assertIn("추정", setting["error"])

    def test_recent_comparison_summary_only_opens_an_existing_output_folder(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "output"
            run = out / "비교생성" / "run-1"
            run.mkdir(parents=True)
            progress_file = root / "비교생성-진행.json"
            progress_file.write_text(json.dumps({
                "folder": "비교생성/run-1",
                "status": "stopped",
                "mode_label": "그림체 × 캐릭터",
                "plan": {"count": 12},
                "completed": {"a": {"file": "비교생성/run-1/a.webp"}},
            }, ensure_ascii=False), encoding="utf-8")
            cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
            cfg["out_dir"] = str(out)
            with patch.object(APP, "COMPARE_PROGRESS_FILE", progress_file):
                summary = APP.comparison_progress_summary(cfg)
                progress_file.write_text(json.dumps({
                    "folder": "../outside", "completed": {},
                }), encoding="utf-8")
                escaped = APP.comparison_progress_summary(cfg)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["folder"], "비교생성/run-1")
        self.assertEqual(summary["completed"], 1)
        self.assertEqual(summary["total"], 12)
        self.assertFalse(escaped["ok"])

    def test_comparison_history_lists_and_activates_each_incomplete_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "output"
            runs = out / "비교생성"
            stopped_dir = runs / "stopped-run"
            complete_dir = runs / "complete-run"
            stopped_dir.mkdir(parents=True)
            complete_dir.mkdir(parents=True)
            base_plan = {
                "count": 4,
                "options": {
                    "mode": "both", "fixed_size": True,
                    "width": 512, "height": 512,
                    "same_seed": True, "seed": 7, "seed_count": 2,
                    "limit": 0, "include_refs": False,
                },
            }
            stopped = {
                "signature": "stopped-signature",
                "folder": "비교생성/stopped-run",
                "status": "stopped",
                "mode_label": "그림체 × 캐릭터",
                "updated_at": "2026-07-28 00:10:00",
                "plan": base_plan,
                "completed": {"a": {"file": "비교생성/stopped-run/a.webp"}},
            }
            complete = {
                "signature": "complete-signature",
                "folder": "비교생성/complete-run",
                "status": "complete",
                "mode_label": "그림체 전체",
                "updated_at": "2026-07-28 00:11:00",
                "plan": {"count": 1, "options": {
                    **base_plan["options"], "mode": "styles", "seed_count": 1,
                }},
                "completed": {"b": {"file": "비교생성/complete-run/b.webp"}},
            }
            (stopped_dir / "manifest.json").write_text(
                json.dumps(stopped, ensure_ascii=False), encoding="utf-8")
            time.sleep(0.01)
            (complete_dir / "manifest.json").write_text(
                json.dumps(complete, ensure_ascii=False), encoding="utf-8")
            progress_file = root / "비교생성-진행.json"
            cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
            cfg["out_dir"] = str(out)

            with patch.object(APP, "COMPARE_PROGRESS_FILE", progress_file):
                listed = APP.comparison_runs(cfg)
                activated = APP.activate_comparison_run(
                    cfg, "비교생성/stopped-run")
                saved = json.loads(progress_file.read_text(encoding="utf-8"))
                before_complete = progress_file.read_bytes()
                completed_result = APP.activate_comparison_run(
                    cfg, "비교생성/complete-run")
                after_complete = progress_file.read_bytes()
                with self.assertRaises(ValueError):
                    APP.activate_comparison_run(cfg, "../outside")

        self.assertEqual(len(listed["runs"]), 2)
        by_name = {run["name"]: run for run in listed["runs"]}
        self.assertTrue(by_name["stopped-run"]["resumable"])
        self.assertFalse(by_name["complete-run"]["resumable"])
        self.assertTrue(activated["resumable"])
        self.assertEqual(activated["completed"], 1)
        self.assertEqual(activated["options"]["seed_count"], 2)
        self.assertEqual(saved["signature"], "stopped-signature")
        self.assertFalse(completed_result["resumable"])
        self.assertEqual(before_complete, after_complete)

    def test_whole_backup_excludes_secrets_and_restores_then_rolls_back(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            char_dir = root / "캐릭터"
            settings_dir = root / "세팅"
            cache = root / "수집" / "이미지캐시"
            remote = cache / "원격"
            for directory in (char_dir, settings_dir, cache, remote):
                directory.mkdir(parents=True, exist_ok=True)
            char_file = char_dir / "A.json"
            char_file.write_text('{"id":"a","이름":"A","외형":"original"}',
                                 encoding="utf-8")
            (settings_dir / "내세팅.json").write_text('{"이름":"내세팅","씬":{}}',
                                                     encoding="utf-8")
            (cache / "local.webp").write_bytes(b"local-source")
            (remote / "download.webp").write_bytes(b"remote-cache")
            (root / "output").mkdir()
            (root / "output" / "result.webp").write_bytes(b"generated")
            cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
            cfg.update(token="pst-never-export", booru_keys={"x": {"key": "secret"}},
                       out_dir=str(root / "output"), base_prompt="backup prompt")
            settings_file = root / "설정.json"
            settings_file.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
            empty = root / "empty"

            with (
                patch.object(APP, "BASE_DIR", root),
                patch.object(APP, "PROFILE_DIR", root),
                patch.object(APP, "SETTINGS_FILE", settings_file),
                patch.object(APP, "BUILDER_FILE", root / "후보사전.json"),
                patch.object(APP, "SPEC_FILE", root / "규격.json"),
                patch.object(APP, "OPTIONS_FILE", root / "옵션.json"),
                patch.object(APP, "TAG_DIR", empty / "태그"),
                patch.object(APP, "SETTINGS_DIR", settings_dir),
                patch.object(APP, "SCHEMA_DIR", empty / "씬규격"),
                patch.object(APP, "SCENESET_DIR", empty / "씬프리셋"),
                patch.object(APP, "STYLE_DIR", empty / "그림체"),
                patch.object(APP, "CHAR_DIR", char_dir),
                patch.object(APP, "FRAG_DIR", empty / "조각"),
                patch.object(APP, "VIBE_DIR", empty / "바이브"),
                patch.object(APP, "PICKS_FILE", root / "선별.json"),
                patch.object(APP, "SCENES_FILE", root / "씬.json"),
            ):
                blob = APP.export_user_backup(cfg)
                with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                    names = set(archive.namelist())
                    saved_cfg = json.loads(
                        archive.read("data/profile/설정.json"))
                self.assertNotIn("token", saved_cfg)
                self.assertNotIn("booru_keys", saved_cfg)
                self.assertNotIn("out_dir", saved_cfg)
                self.assertIn("data/common/수집/이미지캐시/local.webp", names)
                self.assertFalse(any("원격" in name for name in names))
                self.assertFalse(any("output/" in name for name in names))

                char_file.write_text('{"id":"a","이름":"A","외형":"changed"}',
                                     encoding="utf-8")
                current = dict(cfg)
                current.update(token="pst-current", base_prompt="changed prompt")
                settings_file.write_text(json.dumps(current, ensure_ascii=False),
                                         encoding="utf-8")
                preview = APP.preview_user_backup(blob)
                restored = APP.restore_user_backup(blob, preview["sha256"])
                restored_cfg = json.loads(settings_file.read_text(encoding="utf-8"))
                self.assertTrue(restored["ok"])
                self.assertEqual(
                    json.loads(char_file.read_text(encoding="utf-8"))["외형"],
                    "original")
                self.assertEqual(restored_cfg["base_prompt"], "backup prompt")
                self.assertEqual(restored_cfg["token"], "pst-current")
                self.assertEqual(restored_cfg["out_dir"], str(root / "output"))

                # 복원 뒤 사용자가 다시 편집한 파일은 되돌리기가 덮어쓰면 안 된다.
                char_file.write_text(
                    '{"id":"a","이름":"A","외형":"after-restore edit"}',
                    encoding="utf-8",
                )
                rolled = APP.rollback_user_backup(restored["batch"])
                rolled_cfg = json.loads(settings_file.read_text(encoding="utf-8"))
                self.assertTrue(rolled["ok"])
                self.assertEqual(rolled["skipped"], 1)
                self.assertEqual(
                    json.loads(char_file.read_text(encoding="utf-8"))["외형"],
                    "after-restore edit")
                self.assertEqual(rolled_cfg["base_prompt"], "changed prompt")
                self.assertEqual(rolled_cfg["token"], "pst-current")

    def test_whole_backup_rejects_manifest_path_escape(self):
        payload = io.BytesIO()
        raw = b"unsafe"
        manifest = {
            "schema": APP.BACKUP_SCHEMA,
            "files": [{"path": "common/../outside.txt", "size": len(raw),
                       "sha256": hashlib.sha256(raw).hexdigest()}],
        }
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("data/common/../outside.txt", raw)
        with self.assertRaisesRegex(ValueError, "위험하거나 중복"):
            APP.preview_user_backup(payload.getvalue())

    def test_whole_backup_ui_reloads_without_losing_rollback_handle(self):
        page = APP.PAGE_TEMPLATE
        for element_id in (
            "backupCard", "backupExport", "backupChoose", "backupFile",
            "backupRestore", "backupRollback", "backupMsg",
        ):
            self.assertIn(f'id="{element_id}"', page)
        self.assertIn("X-Backup-SHA256", page)
        self.assertIn("sessionStorage.setItem('naisBackupRollback'", page)
        self.assertIn("sessionStorage.getItem('naisBackupRollback')", page)
        self.assertIn("sessionStorage.removeItem('naisBackupRollback')", page)
        self.assertGreaterEqual(page.count("setTimeout(() => location.reload(), 700)"), 2)

    def test_local_image_audit_separates_legacy_names_from_damage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            collect = root / "수집"
            cache = collect / "이미지캐시"
            cache.mkdir(parents=True)
            image = io.BytesIO()
            Image.new("RGB", (4, 3), (20, 40, 60)).save(image, "WEBP")
            payload = image.getvalue()
            legacy = "f" * 64 + ".webp"
            orphan = "orphan.webp"
            (cache / legacy).write_bytes(payload)
            # 같은 내용의 미사용 파일은 중복이지만 삭제 가능 판정은 아니다.
            (cache / orphan).write_bytes(payload)
            (collect / "그림체.json").write_text(json.dumps([{
                "id": "legacy-style",
                "images": ["local:" + legacy],
            }], ensure_ascii=False), encoding="utf-8")

            with patch.object(APP, "BASE_DIR", root), \
                    patch.object(APP, "IMG_CACHE", cache):
                result = APP.local_image_integrity()

            self.assertTrue(result["ok"])
            self.assertEqual(result["unique_references"], 1)
            self.assertEqual(result["missing"], 0)
            self.assertEqual(result["unreadable_references"], 0)
            self.assertEqual(result["referenced_legacy_names"], 1)
            self.assertEqual(result["unreferenced"], 1)
            self.assertEqual(result["duplicate_groups"], 1)
            self.assertFalse(result["normalization"]["blocked"])
            self.assertIn("자동 삭제하지 않습니다", result["note"])

    def test_local_image_normalize_preserves_old_file_and_rolls_back_json(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            collect = root / "수집"
            cache = collect / "이미지캐시"
            cache.mkdir(parents=True)
            image = io.BytesIO()
            Image.new("RGB", (5, 4), (70, 30, 10)).save(image, "WEBP")
            payload = image.getvalue()
            legacy = "legacy-before-webp-conversion.webp"
            canonical = hashlib.sha256(payload).hexdigest() + ".webp"
            source = cache / legacy
            source.write_bytes(payload)
            data_file = collect / "그림체.json"
            original = [{"id": "a", "images": ["local:" + legacy]}]
            data_file.write_text(json.dumps(original, ensure_ascii=False),
                                 encoding="utf-8")

            with patch.object(APP, "BASE_DIR", root), \
                    patch.object(APP, "IMG_CACHE", cache):
                preview = APP.local_image_integrity()
                applied = APP.normalize_local_image_refs(
                    preview["fingerprint"])
                normalized = json.loads(data_file.read_text(encoding="utf-8"))
                self.assertTrue(applied["ok"])
                self.assertEqual(
                    normalized[0]["images"], ["local:" + canonical])
                self.assertEqual(source.read_bytes(), payload)
                self.assertEqual((cache / canonical).read_bytes(), payload)

                undone = APP.rollback_local_image_normalize(applied["batch"])
                restored = json.loads(data_file.read_text(encoding="utf-8"))
                self.assertTrue(undone["ok"])
                self.assertEqual(restored, original)
                self.assertTrue(source.exists())
                self.assertFalse((cache / canonical).exists())
                held = (root / "수집" / "이미지무결성기록"
                        / applied["batch"] / "되돌린-새이름" / canonical)
                self.assertEqual(held.read_bytes(), payload)

    def test_local_image_normalize_refuses_missing_references(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            collect = root / "수집"
            cache = collect / "이미지캐시"
            cache.mkdir(parents=True)
            data_file = collect / "그림체.json"
            data_file.write_text(
                '[{"images":["local:missing.webp"]}]', encoding="utf-8")

            with patch.object(APP, "BASE_DIR", root), \
                    patch.object(APP, "IMG_CACHE", cache):
                preview = APP.local_image_integrity()
                result = APP.normalize_local_image_refs(
                    preview["fingerprint"])

            self.assertEqual(preview["missing"], 1)
            self.assertTrue(preview["normalization"]["blocked"])
            self.assertFalse(result["ok"])
            self.assertEqual(
                json.loads(data_file.read_text(encoding="utf-8")),
                [{"images": ["local:missing.webp"]}],
            )

    def test_local_image_rollback_does_not_overwrite_later_user_edit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            collect = root / "수집"
            cache = collect / "이미지캐시"
            cache.mkdir(parents=True)
            image = io.BytesIO()
            Image.new("RGB", (3, 3), (1, 2, 3)).save(image, "WEBP")
            payload = image.getvalue()
            legacy = "legacy.webp"
            (cache / legacy).write_bytes(payload)
            data_file = collect / "그림체.json"
            data_file.write_text(json.dumps(
                [{"id": "before", "images": ["local:" + legacy]}]),
                encoding="utf-8")

            with patch.object(APP, "BASE_DIR", root), \
                    patch.object(APP, "IMG_CACHE", cache):
                preview = APP.local_image_integrity()
                applied = APP.normalize_local_image_refs(
                    preview["fingerprint"])
                edited = [{"id": "edited-after-normalize", "images": []}]
                data_file.write_text(json.dumps(edited), encoding="utf-8")
                undone = APP.rollback_local_image_normalize(applied["batch"])

            self.assertTrue(undone["ok"])
            self.assertEqual(undone["restored"], 0)
            self.assertEqual(undone["skipped"], 1)
            self.assertEqual(
                json.loads(data_file.read_text(encoding="utf-8")), edited)

    def test_local_image_integrity_ui_has_scan_normalize_and_rollback(self):
        page = APP.PAGE_TEMPLATE
        for element_id in (
            "localImageCard", "localImageScan", "localImageNormalize",
            "localImageRollback", "localImageMsg",
        ):
            self.assertIn(f'id="{element_id}"', page)
        self.assertIn("/api/local_image_integrity", page)
        self.assertIn("/api/local_image_normalize", page)
        self.assertIn("/api/local_image_rollback", page)
        self.assertIn("옛 파일은 지우지 않고", page)

    def test_build_main_writes_the_data_pack_beside_the_program(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            app_dir = root / "dist" / BUILD.APP_NAME
            app_dir.mkdir(parents=True)
            exe = app_dir / f"{BUILD.APP_NAME}.exe"
            exe.write_bytes(b"fixture")
            seen = {}

            def fake_data_pack(out_dir):
                seen["out_dir"] = out_dir
                target = out_dir / BUILD.DATA_PACK_NAME
                target.write_bytes(b"fixture")
                return target

            with (
                patch.object(BUILD, "HERE", root),
                patch.object(BUILD, "make_icon", return_value=None),
                patch.object(BUILD, "make_version_file",
                             return_value=root / "build" / "version.txt"),
                patch.object(BUILD, "build_exe", return_value=exe),
                patch.object(BUILD, "copy_assets", return_value=([], [])),
                patch.object(BUILD, "build_data_pack",
                             side_effect=fake_data_pack),
                patch.object(BUILD.sys, "argv", ["빌드.py"]),
            ):
                self.assertEqual(BUILD.main(), 0)

        self.assertEqual(seen["out_dir"], root / "dist")

    def test_empty_program_does_not_recreate_bundled_content(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with (
                patch.object(APP, "BASE_DIR", root),
                patch.object(APP, "SETTINGS_DIR", root / "세팅"),
                patch.object(APP, "SCHEMA_DIR", root / "씬규격"),
                patch.object(APP, "CONFIG_FILE", root / "asset_config.json"),
                patch.object(APP, "OPTIONS_FILE", root / "옵션.json"),
                patch.object(APP, "SPEC_FILE", root / "규격.json"),
            ):
                self.assertEqual(APP.list_settings(), [])
                self.assertFalse((root / "세팅").exists())
                self.assertFalse((root / "씬규격").exists())
                self.assertTrue(APP.load_options())
                self.assertTrue(APP.load_spec())
                self.assertFalse((root / "옵션.json").exists())
                self.assertFalse((root / "규격.json").exists())
        page = APP.PAGE_TEMPLATE
        self.assertIn("아직 넣은 세팅이 없습니다.", page)
        self.assertIn("빌더 후보 자료가 아직 없습니다.", page)
        self.assertIn("앱 본체에는 <b>후보사전·태그·세팅·수집 자료가 들어 있지 않습니다.", page)

    def test_basic_data_pack_installs_and_undoes_each_data_kind(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w") as archive:
                archive.writestr(
                    "후보사전.json",
                    json.dumps({"캐릭터단계": [], "베이스단계": []},
                               ensure_ascii=False),
                )
                archive.writestr(
                    "규격.json",
                    json.dumps({"캐릭터_그룹": [], "그림체_그룹": []},
                               ensure_ascii=False),
                )
                archive.writestr(
                    "옵션.json",
                    json.dumps({"장소테마": {"시험": "test"}}, ensure_ascii=False),
                )
                archive.writestr(
                    "세팅/시험.json",
                    json.dumps({"이름": "시험", "방식": "단독",
                                "씬": {"1": {"name": "시험"}}},
                               ensure_ascii=False),
                )
                archive.writestr("태그/시험.csv", "tag,0,1,\n")

            with (
                patch.object(APP, "BASE_DIR", root),
                patch.object(APP, "BUILDER_FILE", root / "후보사전.json"),
                patch.object(APP, "SPEC_FILE", root / "규격.json"),
                patch.object(APP, "OPTIONS_FILE", root / "옵션.json"),
                patch.object(APP, "SETTINGS_DIR", root / "세팅"),
                patch.object(APP, "TAG_DIR", root / "태그"),
                patch.object(APP, "IMG_CACHE", root / "수집" / "이미지캐시"),
            ):
                result = APP.import_datapack_bytes(
                    payload.getvalue(), "기본자료팩.zip")
                self.assertTrue(result["ok"])
                self.assertEqual(result["added"], 5)
                for rel in (
                    "후보사전.json", "규격.json", "옵션.json",
                    "세팅/시험.json", "태그/시험.csv",
                ):
                    self.assertTrue((root / rel).exists(), rel)
                undone = APP.undo_datapack(result["batch"])
                self.assertTrue(undone["ok"])
                for rel in (
                    "후보사전.json", "규격.json", "옵션.json",
                    "세팅/시험.json", "태그/시험.csv",
                ):
                    self.assertFalse((root / rel).exists(), rel)

    def test_data_pack_overwrite_undo_restores_previous_whole_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = {"캐릭터단계": [{"이름": "내 자료"}], "베이스단계": []}
            new = {"캐릭터단계": [{"이름": "새 자료"}], "베이스단계": []}
            (root / "후보사전.json").write_text(
                json.dumps(old, ensure_ascii=False), encoding="utf-8")
            with (
                patch.object(APP, "BASE_DIR", root),
                patch.object(APP, "BUILDER_FILE", root / "후보사전.json"),
                patch.object(APP, "SPEC_FILE", root / "규격.json"),
                patch.object(APP, "OPTIONS_FILE", root / "옵션.json"),
                patch.object(APP, "SETTINGS_DIR", root / "세팅"),
                patch.object(APP, "TAG_DIR", root / "태그"),
                patch.object(APP, "IMG_CACHE", root / "수집" / "이미지캐시"),
            ):
                result = APP.import_datapack_bytes(
                    json.dumps(new, ensure_ascii=False).encode(),
                    "후보사전.json", overwrite=True)
                self.assertTrue(result["ok"])
                self.assertEqual(
                    json.loads((root / "후보사전.json").read_text(
                        encoding="utf-8")),
                    new,
                )
                undone = APP.undo_datapack(result["batch"])
                self.assertTrue(undone["ok"])
                self.assertEqual(
                    json.loads((root / "후보사전.json").read_text(
                        encoding="utf-8")),
                    old,
                )

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
        # HTTP-date는 숫자형과 똑같이 1~600초로 제한한다. 과거 날짜가
        # 음수 대기나 즉시 재시도 루프가 되면 안 된다.
        self.assertEqual(
            APP.retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT"), 1.0)
        self.assertEqual(
            APP.retry_after_seconds("Wed, 21 Oct 2037 07:28:00 GMT"), 600.0)

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

    def test_style_restore_keeps_conflicting_deleted_data_in_trash(self):
        """같은 id가 다시 생겨도 새 자료를 덮거나 옛 자료를 휴지통에서 잃지 않는다."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            style_file = root / "수집" / "그림체.json"
            trash_file = root / "수집" / "지운그림체.json"
            style_file.parent.mkdir(parents=True)
            style_file.write_text(json.dumps([
                {"id": "same", "base": "new current data"},
            ], ensure_ascii=False), encoding="utf-8")
            trash_file.write_text(json.dumps([
                {"id": "same", "base": "old deleted data", "_지운때": "batch"},
                {"id": "unique", "base": "recover me", "_지운때": "batch"},
            ], ensure_ascii=False), encoding="utf-8")
            with patch.object(APP, "BASE_DIR", root), \
                    patch.object(APP, "STYLE_FILE", style_file):
                result = APP.restore_styles(["same", "unique"])
                current = json.loads(style_file.read_text(encoding="utf-8"))
                remaining = json.loads(trash_file.read_text(encoding="utf-8"))

            self.assertEqual(result["되살림"], 1)
            self.assertEqual(result["충돌"], 1)
            self.assertEqual(
                {row["id"]: row["base"] for row in current},
                {"same": "new current data", "unique": "recover me"},
            )
            self.assertEqual(
                [(row["id"], row["base"]) for row in remaining],
                [("same", "old deleted data")],
            )

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
        self.assertEqual(source.count("runtime_generation_params("), 7)
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

    def test_studio_layout_is_default_and_classic_remains_compatible(self):
        """작업실을 기본으로 쓰되 설정 한 번으로 기존 호환 화면을 복원해야 한다."""
        page = APP.render_page()
        css = (ROOT / "ui" / "studio.css").read_text(encoding="utf-8")
        self.assertIn('href="/ui/studio.css"', page)
        self.assertIn('id="layoutChips"', page)
        self.assertIn(
            "const LAYOUTS = [['studio','작업실'],['classic','기존 호환']]",
            page,
        )
        self.assertIn(
            "const layout = u.layout === 'classic' ? 'classic' : 'studio'",
            page,
        )
        self.assertIn(
            "const studio = (STATE.ui || {}).layout !== 'classic'",
            page,
        )
        self.assertIn("r.setAttribute('data-layout', 'studio')", page)
        self.assertIn("r.removeAttribute('data-layout')", page)
        self.assertIn(':root[data-layout="studio"] .titlebar', css)
        self.assertIn('body:not([data-mode="preview"]) .left', css)
        self.assertIn('@media (max-width: 1479px)', css)
        self.assertNotIn("수집", BUILD.ASSET_DIRS)

    def test_studio_library_moves_one_comparison_card_and_classic_restores_it(self):
        """비교 생성은 복제하지 않고 작업실/기존 화면 사이에서 같은 DOM을 옮겨야 한다."""
        page = APP.render_page()
        css = (ROOT / "ui" / "studio.css").read_text(encoding="utf-8")
        self.assertEqual(page.count('id="compareCard"'), 1)
        for marker in ('id="compareClassicHome"', 'id="studioCompareHome"',
                       'id="studioLibraryNav"', 'id="studioLibraryBrowse"'):
            self.assertIn(marker, page)
        self.assertIn("home.insertAdjacentElement('afterend', card)", page)
        self.assertIn("STATE.ui.library_work = button.dataset.libraryWork", page)
        self.assertIn("document.body.dataset.mode !== 'library'", page)
        self.assertIn("arrangeStudioWorkspace();", page)
        self.assertIn('.studio-subnav-actions button.on', css)

    def test_studio_settings_separates_existing_cards_and_classic_shows_all(self):
        """작업실은 세 작업을 나누되 기존 화면에서는 원래 카드가 모두 복원돼야 한다."""
        page = APP.render_page()
        css = (ROOT / "ui" / "studio.css").read_text(encoding="utf-8")
        settings_view = page[
            page.index('id="vSettings"'):page.index('id="vBuilder"')
        ]
        for marker in ('id="studioSettingsNav"', 'id="settingSelectCard"',
                       'id="sceneQuickCard"', 'id="settingBuilderCard"'):
            self.assertEqual(page.count(marker), 1)
            self.assertIn(marker, settings_view)
        self.assertIn("STATE.ui.settings_work = next", page)
        self.assertIn("settingsCard.classList.toggle('hidden', studio && key !== settingsWork)", page)
        self.assertIn("settingsNav.classList.toggle('hidden', !studio)", page)
        self.assertIn("#studioSettingsNav .studio-subnav-actions", css)

    def test_character_duplicate_uses_latest_client_state_and_unique_identity(self):
        """캐릭터 변형은 기존 전체 프롬프트를 깊은 복사하고 id·이름만 새로 만든다."""
        page = APP.render_page()
        self.assertIn('data-xdup="${c.id}"', page)
        self.assertIn("const cloned = JSON.parse(JSON.stringify(chars[at]));", page)
        self.assertIn("cloned.id = genId();", page)
        self.assertIn("chars.splice(at + 1, 0, cloned);", page)
        self.assertIn("while(names.has(name.toLocaleLowerCase()))", page)
        self.assertIn("renderLibrary(); renderSlots(); save();", page)

    def test_character_delete_requires_confirmation_and_can_be_undone(self):
        page = APP.render_page()
        self.assertIn('id="charUndo" class="hidden"', page)
        self.assertIn("const DELETED_CHARS = [];", page)
        self.assertIn("if(!confirm(`'${character.name || '캐릭터'}'을 삭제할까요?", page)
        self.assertIn("DELETED_CHARS.push({character:JSON.parse(JSON.stringify(character)), index:at});", page)
        self.assertIn("const deleted = DELETED_CHARS.pop();", page)
        self.assertIn("chars.splice(Math.min(deleted.index, chars.length), 0, restored);", page)
        self.assertIn("if(chars.some(x => x.id === restored.id)) restored.id = genId();", page)

    def test_newer_external_character_file_is_not_overwritten_by_stale_settings(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            settings = root / "설정.json"
            char_dir = root / "캐릭터"
            char_dir.mkdir()
            cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
            cfg["characters"] = [{
                "id": "same-id", "name": "설정의 옛 이름",
                "female": "old appearance", "clothed": "old clothes",
                "negative": "old negative", "enabled": False,
            }]
            settings.write_text("{}", encoding="utf-8")
            external = char_dir / "외부 편집.json"
            time.sleep(0.01)
            external.write_text(json.dumps({
                "id": "same-id", "이름": "외부 편집",
                "외형": "new appearance", "착의": "new clothes",
                "네거티브": "new negative", "출처": "user file",
                "그룹": {"예술적 변형": "watercolor"},
                "미래필드": {"keep": "unknown character metadata"},
            }, ensure_ascii=False), encoding="utf-8")

            with (
                patch.object(APP, "SETTINGS_FILE", settings),
                patch.object(APP, "CHAR_DIR", char_dir),
            ):
                APP.import_char_files(cfg)
                APP.sync_chars_to_files(cfg)
                APP.save_config(cfg)
                saved_file = json.loads(
                    (char_dir / "외부 편집.json").read_text(encoding="utf-8"))
                saved_settings = json.loads(settings.read_text(encoding="utf-8"))

            char = cfg["characters"][0]
            self.assertEqual(char["name"], "외부 편집")
            self.assertEqual(char["female"], "new appearance")
            self.assertEqual(char["clothed"], "new clothes")
            self.assertEqual(char["negative"], "new negative")
            self.assertEqual(char["source"], "user file")
            self.assertEqual(char["groups"], {"예술적 변형": "watercolor"})
            self.assertFalse(char["enabled"], "화면의 켜기/끄기 상태는 보존해야 한다")
            self.assertEqual(saved_file["외형"], "new appearance")
            self.assertEqual(saved_file["착의"], "new clothes")
            self.assertEqual(
                saved_file["미래필드"],
                {"keep": "unknown character metadata"},
            )
            self.assertEqual(
                saved_settings["characters"][0]["female"], "new appearance")

    def test_older_character_file_does_not_undo_a_newer_ui_save(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            settings = root / "설정.json"
            char_dir = root / "캐릭터"
            char_dir.mkdir()
            external = char_dir / "옛 파일.json"
            external.write_text(json.dumps({
                "id": "same-id", "이름": "옛 파일", "외형": "old appearance",
            }, ensure_ascii=False), encoding="utf-8")
            time.sleep(0.01)
            settings.write_text("{}", encoding="utf-8")
            cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
            cfg["characters"] = [{
                "id": "same-id", "name": "UI 최신값",
                "female": "new appearance", "enabled": True,
            }]

            with (
                patch.object(APP, "SETTINGS_FILE", settings),
                patch.object(APP, "CHAR_DIR", char_dir),
            ):
                APP.import_char_files(cfg)

            self.assertEqual(cfg["characters"][0]["name"], "UI 최신값")
            self.assertEqual(cfg["characters"][0]["female"], "new appearance")

    def test_unchanged_character_sync_does_not_rewrite_or_make_backup(self):
        with tempfile.TemporaryDirectory() as td:
            char_dir = Path(td) / "캐릭터"
            char_dir.mkdir()
            target = char_dir / "Stable.json"
            document = {
                "id": "stable-id",
                "이름": "Stable",
                "외형": "1girl, stable identity",
                "착의": "blue dress",
                "네거티브": "bad anatomy",
                "미래필드": {"must": "survive"},
            }
            target.write_text(
                json.dumps(document, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            before = target.read_bytes()
            before_mtime = target.stat().st_mtime_ns
            cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
            cfg["characters"] = [{
                "id": "stable-id",
                "name": "Stable",
                "female": "1girl, stable identity",
                "clothed": "blue dress",
                "negative": "bad anatomy",
                "enabled": True,
            }]

            with patch.object(APP, "CHAR_DIR", char_dir):
                APP.sync_chars_to_files(cfg)

            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(target.stat().st_mtime_ns, before_mtime)
            self.assertFalse(list(char_dir.rglob("*.bak")))

    def test_same_character_names_never_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as td:
            char_dir = Path(td) / "캐릭터"
            cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
            cfg["characters"] = [
                {
                    "id": "same-name-a", "name": "Same",
                    "female": "first identity", "enabled": True,
                },
                {
                    "id": "same-name-b", "name": "Same",
                    "female": "second identity", "enabled": True,
                },
            ]

            with patch.object(APP, "CHAR_DIR", char_dir):
                APP.sync_chars_to_files(cfg)
                APP.sync_chars_to_files(cfg)

            files = sorted(char_dir.glob("Same*.json"))
            self.assertEqual([p.name for p in files], ["Same (2).json", "Same.json"])
            documents = [
                json.loads(p.read_text(encoding="utf-8")) for p in files
            ]
            self.assertEqual(
                {doc["id"] for doc in documents},
                {"same-name-a", "same-name-b"},
            )
            self.assertEqual(
                {doc["외형"] for doc in documents},
                {"first identity", "second identity"},
            )

    def test_thousand_character_files_import_sync_restart_and_compare_without_loss(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            settings = root / "설정.json"
            char_dir = root / "캐릭터"
            char_dir.mkdir()
            settings.write_text("{}", encoding="utf-8")
            time.sleep(0.01)
            expected_last = ""
            for i in range(1000):
                prompt = (
                    f"1girl, bulk character {i:04d}, long hair, "
                    f"identity token {i:04d}, 1.2::detail::{chr(0xAC00 + i % 100)}"
                )
                if i == 999:
                    expected_last = prompt
                folder = char_dir / f"묶음-{i % 10:02d}"
                folder.mkdir(exist_ok=True)
                (folder / f"캐릭터-{i:04d}.json").write_text(json.dumps({
                    "id": f"bulk-{i:04d}",
                    "이름": f"캐릭터 {i:04d}",
                    "외형": prompt,
                    "착의": f"outfit {i % 40}",
                    "네거티브": f"negative {i % 13}",
                }, ensure_ascii=False), encoding="utf-8")

            cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
            with patch.object(APP, "SETTINGS_FILE", settings), \
                    patch.object(APP, "CHAR_DIR", char_dir):
                APP.import_char_files(cfg)
                APP.sync_chars_to_files(cfg)
                APP.save_config(cfg)
                saved = json.loads(settings.read_text(encoding="utf-8"))
                restarted = dict(APP.DEFAULT_CONFIG)
                restarted.update(saved)
                APP.import_char_files(restarted)
                compared = APP.comparison_characters(restarted)

            self.assertEqual(len(cfg["characters"]), 1000)
            self.assertEqual(len(restarted["characters"]), 1000)
            self.assertEqual(len(compared), 1000)
            self.assertEqual(restarted["characters"][-1]["female"], expected_last)
            self.assertEqual(
                APP._comparison_character_prompt(compared[-1]),
                expected_last + ", outfit 39",
            )
            self.assertEqual(len(restarted["character_folders"]), 10)

    def test_large_character_library_renders_bounded_searchable_pages(self):
        page = APP.render_page()
        for element_id in (
            "libFilter", "libType", "libCount", "libMore",
            "charFilter", "charCount", "charMore",
        ):
            self.assertIn(f'id="{element_id}"', page)
        self.assertIn("filtered.slice(0, LIB_LIMIT)", page)
        self.assertIn("filtered.slice(0, CHAR_EDIT_LIMIT)", page)
        self.assertIn("LIB_LIMIT += 100", page)
        self.assertIn("CHAR_EDIT_LIMIT += 24", page)
        self.assertIn("libraryNeedle", page)
        self.assertIn(
            "var LIB_FILTER_TIMER = null, CHAR_FILTER_TIMER = null;",
            page,
        )
        self.assertIn("clearTimeout(CHAR_FILTER_TIMER);", page)

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

    def test_long_prompts_survive_a_save_load_round_trip_byte_for_byte(self):
        """프롬프트는 **사용자 원본 자료**다. 저장했다 불러오면 바이트까지 같아야 한다.

        줄바꿈·가중치(`1.2::`)·괄호(`(nier:automata)`)·파이프(`||a|b||`)·중괄호 조각·
        유니코드가 섞인 긴 원문으로 확인한다. 글자 수로 자르는 길이 하나라도 생기면
        여기서 걸린다."""
        long_tail = ", ".join(f"artist:tester{i}" for i in range(400))   # 6천 자가 넘는다
        base = (
            "1girl, solo,\n"
            "1.2::artist:ratatatat74 ::, 0.4::artist:ctrlz77 ::,\n"
            "2b (nier:automata), 1920s (style), {a|b|c}, ||red||,\n"
            "-1::film grain ::, [[weak]], <조각이름>, <*차례조각>,\n"
            "한글 태그, emoji 🎨, quote \" and ' and \\ backslash,\n"
            + long_tail
        )
        negative = ("lowres, bad anatomy,\n||x|y||, (parens), 1.5::strong::,\n"
                    + ", ".join(f"neg{i}" for i in range(300)))
        char1 = "girl, long black hair,\n1.3::detailed eyes::, (nier:automata)\n" + long_tail
        self.assertGreater(len(base), 6000, "시험 원문이 충분히 길어야 의미가 있다")

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "설정.json"
            cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
            cfg["base_prompt"] = base
            cfg["negative_prompt"] = negative
            cfg["char_slots"] = [{"prompt": char1, "outfit": "red dress\n1.1::lace::",
                                  "negative": negative, "enabled": True}]
            with patch.object(APP, "SETTINGS_FILE", path):
                APP.save_config(cfg)
                back = APP.load_json_recover(path)
            self.assertEqual(back["base_prompt"], base, "베이스 프롬프트가 왕복에서 달라졌다")
            self.assertEqual(back["negative_prompt"], negative, "네거티브가 왕복에서 달라졌다")
            self.assertEqual(back["char_slots"][0]["prompt"], char1, "캐릭터 프롬프트가 달라졌다")
            # 바이트 단위로도 같아야 한다 (인코딩·개행 변환이 끼어들지 않는지)
            self.assertEqual(back["base_prompt"].encode("utf-8"), base.encode("utf-8"))
            self.assertEqual(back["char_slots"][0]["outfit"].encode("utf-8"),
                             "red dress\n1.1::lace::".encode("utf-8"))

            # 그림체 자료도 같은 규칙 — 저장했다 읽으면 그대로여야 한다
            style = Path(td) / "그림체.json"
            with patch.object(APP, "STYLE_FILE", style):
                APP._write_styles_raw([{"id": "long-1", "base": base,
                                        "negative": negative, "rest": base,
                                        "characters": [{"prompt": char1}]}])
                rows = APP._load_styles_raw()
            self.assertEqual(rows[0]["base"], base, "그림체 base 가 왕복에서 잘렸다")
            self.assertEqual(rows[0]["negative"], negative)
            self.assertEqual(rows[0]["rest"], base, "`rest` 가 다시 잘리기 시작했다")
            self.assertEqual(rows[0]["characters"][0]["prompt"], char1)

    def test_prompt_fields_have_no_length_caps(self):
        """화면 입력칸에 `maxlength` 를 달지 않는다 — 달면 긴 원문을 **붙여넣는 순간**
        잘린다. 미리보기 말줄임(카드·요약)은 괜찮지만 입력·편집칸은 안 된다."""
        page = APP.render_page()
        self.assertFalse("maxlength" in page.lower(),
                         "입력칸에 maxlength 가 생겼다 — 긴 프롬프트가 붙여넣기에서 잘린다")

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

    def test_metadata_thumbnail_local_name_matches_saved_webp_sha256(self):
        metadata = PngInfo()
        metadata.add_text("Comment", json.dumps({
            "prompt": "1girl, exact thumbnail hash",
            "uc": "bad anatomy",
            "seed": 123,
            "software": "NovelAI",
            "future_setting_not_known_yet": {"mode": "keep-me", "value": 17},
        }))
        source = io.BytesIO()
        Image.new("RGB", (640, 960), (12, 34, 56)).save(
            source, "PNG", pnginfo=metadata)

        with tempfile.TemporaryDirectory() as td, patch.object(
                APP, "IMG_CACHE", Path(td)):
            result = APP.ConfigServer(
                copy.deepcopy(APP.DEFAULT_CONFIG)
            ).handle_inspect(source.getvalue(), "fixture.png", "")
            self.assertTrue(result["ok"])
            local_ref = result["style"]["images"][0]
            self.assertTrue(local_ref.startswith("local:"))
            cached = Path(td) / local_ref.removeprefix("local:")
            payload = cached.read_bytes()
            self.assertEqual(cached.stem, hashlib.sha256(payload).hexdigest())
            self.assertEqual(len(cached.stem), 64)
            fetched, content_type = APP.fetch_cached_image(local_ref)
            self.assertEqual(fetched, payload)
            self.assertEqual(content_type, "image/webp")
            self.assertEqual(
                json.loads(json.dumps(result["style"]))["metadata_raw"][
                    "future_setting_not_known_yet"],
                {"mode": "keep-me", "value": 17},
            )

    def test_datapack_rewrites_wrong_local_image_name_to_content_hash(self):
        image = io.BytesIO()
        Image.new("RGB", (3, 2), (90, 40, 10)).save(image, "WEBP")
        payload = image.getvalue()
        correct = hashlib.sha256(payload).hexdigest() + ".webp"
        styles = [{
            "id": "wrong-local-name",
            "base": "1girl",
            "images": ["local:not-the-content-hash.webp"],
        }]
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            # JSON이 그림보다 먼저 와도 사전 실측으로 참조가 고쳐져야 한다.
            z.writestr("수집/그림체.json", json.dumps(
                styles, ensure_ascii=False))
            z.writestr("수집/이미지캐시/not-the-content-hash.webp", payload)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch.object(APP, "BASE_DIR", root), \
                    patch.object(APP, "STYLE_FILE", root / "수집" / "그림체.json"), \
                    patch.object(APP, "IMG_CACHE", root / "수집" / "이미지캐시"):
                result = APP.import_datapack_bytes(
                    archive.getvalue(), "wrong-name.zip")
                self.assertTrue(result["ok"])
                self.assertTrue((APP.IMG_CACHE / correct).exists())
                self.assertFalse(
                    (APP.IMG_CACHE / "not-the-content-hash.webp").exists())
                saved = json.loads(APP.STYLE_FILE.read_text(encoding="utf-8"))
                self.assertEqual(saved[0]["images"], ["local:" + correct])
                fetched, content_type = APP.fetch_cached_image(
                    saved[0]["images"][0])
                self.assertEqual(fetched, payload)
                self.assertEqual(content_type, "image/webp")
                self.assertTrue(any(
                    "이름이 달랐던 1개" in line for line in result["report"]))

    def test_datapack_preserves_and_restores_conflicting_local_image(self):
        incoming = b"actual image payload"
        previous = b"pre-existing damaged payload"
        correct = hashlib.sha256(incoming).hexdigest() + ".webp"
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("수집/이미지캐시/" + correct, incoming)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cache = root / "수집" / "이미지캐시"
            cache.mkdir(parents=True)
            (cache / correct).write_bytes(previous)
            with patch.object(APP, "BASE_DIR", root), \
                    patch.object(APP, "IMG_CACHE", cache):
                result = APP.import_datapack_bytes(
                    archive.getvalue(), "conflict.zip")
                self.assertTrue(result["ok"])
                self.assertEqual((cache / correct).read_bytes(), incoming)
                undone = APP.undo_datapack(result["batch"])
                self.assertTrue(undone["ok"])
                self.assertEqual((cache / correct).read_bytes(), previous)

    def test_metadata_keeps_each_character_prompt_and_negative_as_whole_text(self):
        values = {
            "v4_prompt": {"caption": {
                "base_caption": "2girls, outdoors",
                "char_captions": [
                    {"char_caption": "character one, red hair, 1.2::smile::",
                     "centers": [{"x": 0.2, "y": 0.5}]},
                    {"char_caption": "character two, blue hair, {hat|ribbon}",
                     "centers": [{"x": 0.8, "y": 0.5}]},
                ],
            }},
            "v4_negative_prompt": {"caption": {
                "base_caption": "bad anatomy",
                "char_captions": [
                    {"char_caption": "character one negative, closed eyes"},
                    {"char_caption": "character two negative, monochrome"},
                ],
            }},
        }
        _, _, characters = APP._prompt_parts(values)
        self.assertEqual(characters, [
            {
                "prompt": "character one, red hair, 1.2::smile::",
                "negative": "character one negative, closed eyes",
                "centers": [{"x": 0.2, "y": 0.5}],
            },
            {
                "prompt": "character two, blue hair, {hat|ribbon}",
                "negative": "character two negative, monochrome",
                "centers": [{"x": 0.8, "y": 0.5}],
            },
        ])

    def test_artist_memo_round_trip_does_not_silently_truncate(self):
        memo = (
            "작가 메모 원문\n" + "가중치 1.2::artist:test:: | 설명 🙂 \\\\ " * 80
        )
        self.assertGreater(len(memo), 500)
        with tempfile.TemporaryDirectory() as td, patch.object(
                APP, "RATINGS_FILE", Path(td) / "작가평가.json"):
            old_cache = copy.deepcopy(APP._RATINGS)
            try:
                APP._RATINGS.update({"mtime": -1, "data": {}})
                saved = APP.rate_artist("Test Artist", memo=memo)
                self.assertEqual(saved["memo"], memo)
                APP._RATINGS.update({"mtime": -1, "data": {}})
                self.assertEqual(
                    APP.load_ratings()["test artist"]["memo"], memo)
            finally:
                APP._RATINGS.clear()
                APP._RATINGS.update(old_cache)

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
        self.assertEqual(source.count("call_nai_api("), 7)  # definition + six callers
        self.assertEqual(source.count("pace_complete()"), 7)  # definition + six callers
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
            self.assertEqual(first["ratings"], {})
            self.assertEqual(first["tags"], {})
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

    def test_image_ratings_tags_and_candidate_groups_are_bounded_labels(self):
        with tempfile.TemporaryDirectory() as td:
            picks_file = Path(td) / "선별.json"
            raw_tags = [f"tag-{i}" for i in range(15)] + ["tag-1", "x" * 80]
            with patch.object(APP, "PICKS_FILE", picks_file):
                saved = APP.save_picks({
                    "picked": ["a.webp", "a.webp"],
                    "fav": [],
                    "folders": {
                        "  후보군 이름  ": ["a.webp", "a.webp", "b.webp"],
                        "x" * 41: ["c.webp"],
                        "x" * 42: ["d.webp"],
                    },
                    "ranks": {},
                    "ratings": {"a.webp": 9, "b.webp": 0, "bad.webp": "bad"},
                    "tags": {"a.webp": raw_tags, "empty.webp": ["", " "]},
                })
                loaded = APP.load_picks()

            self.assertEqual(saved, loaded)
            self.assertEqual(loaded["picked"], ["a.webp"])
            self.assertEqual(
                loaded["folders"]["후보군 이름"], ["a.webp", "b.webp"])
            self.assertEqual(
                loaded["folders"]["x" * 40], ["c.webp", "d.webp"])
            self.assertEqual(loaded["ratings"], {"a.webp": 5})
            self.assertEqual(len(loaded["tags"]["a.webp"]), 12)
            self.assertTrue(all(
                len(tag) <= 40 for tag in loaded["tags"]["a.webp"]))
            self.assertNotIn("empty.webp", loaded["tags"])

    def test_explorer_exposes_rating_tags_and_virtual_candidate_groups(self):
        page = APP.render_page()
        for element_id in (
            "expGroupFilter", "expGroupName", "expGroupSave",
            "expGroupDelete", "expRate", "expTagInput", "expTagSave",
        ):
            self.assertIn(f'id="{element_id}"', page)
        self.assertIn("ratings:EXP.ratings || {}", page)
        self.assertIn("tags:EXP.tags || {}", page)
        self.assertIn("folders:EXP.folders || {}", page)
        self.assertIn("원본 파일은 이동하지 않습니다.", page)

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
