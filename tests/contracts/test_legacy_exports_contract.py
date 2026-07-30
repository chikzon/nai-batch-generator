# -*- coding: utf-8 -*-
"""레거시 축소 단계 1 — 호환 표면 고정 계약.

외부(회귀·계약 시험·CLI)가 쓰는 이름 전수를 LEGACY_EXPORTS로 고정하고,
이동 중에도 이름·endpoint·저장 경로·생성 payload가 흔들리지 않게 잡는다.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.nai_studio.compat.legacy_exports import (  # noqa: E402
    LEGACY_EXPORTS,
    ROUTE_BASELINE,
)

APP = importlib.import_module("src.nai_studio.legacy_app")


def _names_used_by_tests() -> set[str]:
    used: set[str] = {"main"}
    for path in (ROOT / "tests").rglob("*.py"):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        used.update(re.findall(r"\bAPP\.([A-Za-z_][A-Za-z0-9_]*)", text))
        used.update(re.findall(
            r"patch\.object\(\s*APP\s*,\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]",
            text,
        ))
    return used


class LegacyExportSurfaceTests(unittest.TestCase):
    def test_every_export_is_reachable_on_legacy_app(self):
        missing = [
            name for name in LEGACY_EXPORTS if not hasattr(APP, name)
        ]
        self.assertEqual(missing, [], "레거시 호환 이름이 사라졌습니다")

    def test_tests_do_not_use_names_outside_the_contract(self):
        outside = sorted(_names_used_by_tests() - set(LEGACY_EXPORTS))
        self.assertEqual(
            outside, [],
            "시험이 계약 밖 레거시 이름을 쓰기 시작했습니다 — "
            "legacy_exports.py에 소유·종류를 배정해 추가하세요",
        )

    def test_cli_entry_points_are_callable(self):
        self.assertTrue(callable(APP.main))
        start = (ROOT / "start.py").read_text(encoding="utf-8")
        self.assertIn("main", start)

    def test_export_kinds_are_assigned(self):
        allowed = {
            "alias", "adapter", "경로", "상수·상태", "모듈 참조",
            "legacy-class", "기타",
        }
        bad = {
            name: item
            for name, item in LEGACY_EXPORTS.items()
            if item.get("kind") not in allowed or not item.get("owner")
        }
        self.assertEqual(bad, {})


class LegacyBaselineTests(unittest.TestCase):
    def test_route_strings_stay_inside_web_routes(self):
        found: set[str] = set()
        web = ROOT / "src" / "nai_studio" / "web"
        for src in web.rglob("*.py"):
            text = src.read_text(encoding="utf-8")
            found.update(re.findall(r'"(/api/[a-z_0-9]+)"', text))
            found.update(re.findall(
                r'"(/(?:setout|img|refimg|status\.json|latest\.webp))"',
                text,
            ))
        self.assertEqual(
            sorted(found), sorted(ROUTE_BASELINE),
            "endpoint 목록이 기준선과 다릅니다 — 의도한 변경이면 "
            "ROUTE_BASELINE을 함께 갱신하세요",
        )
        outside: list[str] = []
        for src in (ROOT / "src" / "nai_studio").rglob("*.py"):
            if web in src.parents or src.name == "legacy_exports.py":
                continue
            text = src.read_text(encoding="utf-8")
            for route in ROUTE_BASELINE:
                if f'"{route}"' in text:
                    outside.append(f"{src.name}: {route}")
        self.assertEqual(
            outside, [], "endpoint 문자열이 web 밖으로 새 나갔습니다")

    def test_user_data_paths_keep_their_names(self):
        expected_tails = {
            "SETTINGS_FILE": "설정.json",
            "STATE_FILE": "nsfw_seed_state.json",
            "STYLE_FILE": "그림체.json",
            "PICKS_FILE": "선별.json",
            "SCENES_FILE": "씬.json",
            "COMPARE_PROGRESS_FILE": "비교생성-진행.json",
            "BUILDER_FILE": "후보사전.json",
            "SPEC_FILE": "규격.json",
            "OPTIONS_FILE": "옵션.json",
        }
        for name, tail in expected_tails.items():
            self.assertTrue(
                str(getattr(APP, name)).endswith(tail),
                f"{name} 사용자 자료 경로가 바뀌었습니다",
            )

    def test_generation_payload_digest_baseline(self):
        """이동 전후 payload 안정성 기준선. 의도한 payload 변경이 아니라면
        이 해시는 절대 움직이면 안 된다."""
        from src.nai_studio.domain.nai_payload import build_nai_payload

        payload, _meta = build_nai_payload(
            base_prompt="1girl, blue hair",
            negative_prompt="lowres",
            people=[("1girl", "")],
            width=832,
            height=1216,
            scale=6.2,
            cfg_rescale=0.34,
            steps=28,
            sampler="k_euler_ancestral",
            scheduler="karras",
            uc_preset=3,
            seed=424242,
            variety=False,
            params={"model": "nai-diffusion-4-5-full", "use_coords": False},
        )
        digest = hashlib.sha256(
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        baseline_file = Path(__file__).with_name(
            "legacy_payload_baseline.txt")
        if not baseline_file.exists():
            baseline_file.write_text(digest, encoding="utf-8")
        self.assertEqual(
            digest,
            baseline_file.read_text(encoding="utf-8").strip(),
            "생성 payload가 기준선과 다릅니다 — 레거시 이동 중에는 "
            "payload가 바뀌면 안 됩니다",
        )


if __name__ == "__main__":
    unittest.main()
