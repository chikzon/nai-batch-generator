# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.nai_studio.runtime.data_files import (  # noqa: E402
    _atomic_write_bytes,
    atomic_write_json,
    load_json_recover,
    load_settings_recover,
    recoverable_remove,
    shared_data_transaction,
)
from src.nai_studio.services import merge_plan  # noqa: E402
from src.nai_studio.services.user_backup_store import (  # noqa: E402
    UserBackupOperations,
    UserBackupPaths,
    UserBackupSourcePaths,
    backup_diff_plan,
    export_user_backup,
    preview_user_backup,
    restore_user_backup,
)


def _machine(root: Path) -> UserBackupPaths:
    return UserBackupPaths(
        base_dir=root,
        profile_dir=root,
        sources=UserBackupSourcePaths(
            settings_file=root / "설정.json",
            builder_file=root / "후보사전.json",
            spec_file=root / "규격.json",
            options_file=root / "옵션.json",
            tag_dir=root / "태그",
            settings_dir=root / "세팅",
            schema_dir=root / "씬규격",
            sceneset_dir=root / "씬프리셋",
            style_dir=root / "그림체",
            character_dir=root / "캐릭터",
            fragment_dir=root / "조각",
            vibe_dir=root / "수집" / "바이브",
            picks_file=root / "선별.json",
            scenes_file=root / "씬.json",
        ),
    )


class MergeBaselineContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nais-3way-")
        self.root = Path(self.temp.name)
        self.paths = _machine(self.root)
        self.baseline_file = merge_plan.baseline_path(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def operations(self, with_baseline=True) -> UserBackupOperations:
        extra = {}
        if with_baseline:
            path = self.baseline_file

            def lookup(logical):
                return merge_plan.baseline_entry(
                    merge_plan.load_baseline(path, load_json_recover),
                    logical,
                )

            def record(applied):
                return merge_plan.record_applied_baseline(
                    path, load_json_recover, atomic_write_json, applied)

            extra = {"baseline_lookup": lookup, "record_baseline": record}
        return UserBackupOperations(
            transaction=shared_data_transaction,
            atomic_write_bytes=_atomic_write_bytes,
            atomic_write_json=atomic_write_json,
            load_settings=load_settings_recover,
            rollback=lambda *_: None,
            after_restore=lambda: None,
            now=datetime.now,
            random_bytes=os.urandom,
            warning=lambda *_: None,
            recoverable_remove=recoverable_remove,
            **extra,
        )

    def make_backup(self, files: dict[str, bytes], baselines=None) -> bytes:
        """상대 기기에서 온 백업 ZIP을 직접 조립한다."""
        baselines = baselines or {}
        entries = []
        for logical, raw in sorted(files.items()):
            entry = {
                "path": logical,
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            if logical in baselines:
                base_raw = baselines[logical]
                if base_raw is None:
                    entry["base_sha256"] = "f" * 64
                else:
                    entry["base_sha256"] = hashlib.sha256(
                        base_raw).hexdigest()
                    entry["base_size"] = len(base_raw)
            entries.append(entry)
        manifest = {
            "schema": self.paths.schema,
            "created_at": "2026-07-30T00:00:00",
            "profile": "기본",
            "files": entries,
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
            for logical, raw in files.items():
                archive.writestr("data/" + logical, raw)
            for logical, raw in baselines.items():
                if raw is not None:
                    archive.writestr("baseline/" + logical, raw)
        return output.getvalue()

    def test_backup_without_baseline_stays_two_way(self):
        (self.root / "규격.json").write_text(json.dumps({"steps": 20}), "utf-8")
        blob = self.make_backup(
            {"common/규격.json": json.dumps({"steps": 30}).encode("utf-8")})
        preview = preview_user_backup(self.paths, self.operations(), blob)
        change = preview["changes"][0]
        self.assertEqual(change["decision"], "no-base")
        self.assertFalse(change["base_found"])
        self.assertFalse(change["base_available"])

    def test_three_way_decisions_per_json_pointer(self):
        base = {"steps": 28, "cfg": 6, "sampler": "a"}
        # 내 쪽은 cfg·sampler를 바꿨고, 들어오는 쪽은 steps·sampler를 바꿨다
        (self.root / "규격.json").write_text(
            json.dumps({"steps": 28, "cfg": 7, "sampler": "b"}), "utf-8")
        base_raw = json.dumps(base, ensure_ascii=False, indent=1).encode()
        blob = self.make_backup(
            {"common/규격.json": json.dumps(
                {"steps": 30, "cfg": 6, "sampler": "c"}).encode("utf-8")},
            baselines={"common/규격.json": base_raw},
        )
        preview = preview_user_backup(self.paths, self.operations(), blob)
        by_pointer = {item["pointer"]: item for item in preview["changes"]}
        self.assertEqual(by_pointer["/steps"]["decision"], "take-incoming")
        self.assertEqual(by_pointer["/steps"]["base"], 28)
        self.assertEqual(by_pointer["/cfg"]["decision"], "keep-current")
        self.assertEqual(by_pointer["/sampler"]["decision"], "both-changed")

    def test_restore_records_baseline_then_export_embeds_it(self):
        (self.root / "후보사전.json").write_text(
            json.dumps({"단계": ["옛것"]}), "utf-8")
        incoming = json.dumps({"단계": ["새것"]}).encode("utf-8")
        blob = self.make_backup({"common/후보사전.json": incoming})
        result = restore_user_backup(
            self.paths, self.operations(), blob)
        self.assertTrue(result["ok"])
        ledger = merge_plan.load_baseline(
            self.baseline_file, load_json_recover)
        entry = ledger["files"]["common/후보사전.json"]
        self.assertEqual(entry["value"], {"단계": ["새것"]})
        # 이제 이 기기에서 내보내면 기준값이 함께 실린다
        exported = export_user_backup(self.paths, self.operations(), {})
        with zipfile.ZipFile(io.BytesIO(exported)) as archive:
            names = archive.namelist()
            self.assertIn("baseline/common/후보사전.json", names)
            manifest = json.loads(archive.read("manifest.json"))
        declared = {
            item["path"]: item for item in manifest["files"]}
        self.assertIn(
            "base_sha256", declared["common/후보사전.json"])
        self.assertIn("base_size", declared["common/후보사전.json"])

    def test_settings_baseline_never_contains_token(self):
        (self.root / "설정.json").write_text(json.dumps({"a": 1}), "utf-8")
        incoming = json.dumps(
            {"a": 2, "token": "pst-remote-secret"}).encode("utf-8")
        blob = self.make_backup({"profile/설정.json": incoming})
        # 복원 시 로컬 토큰이 병합돼 저장되지만 기준값 장부에는 남지 않아야 한다
        (self.root / "설정.json").write_text(
            json.dumps({"a": 1, "token": "pst-local-secret"}), "utf-8")
        restore_user_backup(self.paths, self.operations(), blob)
        raw = self.baseline_file.read_text("utf-8")
        self.assertNotIn("pst-", raw)

    def test_binary_baseline_is_hash_only_and_compares_by_hash(self):
        image_dir = self.root / "수집" / "이미지캐시"
        image_dir.mkdir(parents=True)
        old_bytes = b"OLDIMAGEBYTES"
        (image_dir / "x.webp").write_bytes(old_bytes)
        # 장부에 바이너리 기준값(해시만) 기록
        merge_plan.record_applied_baseline(
            self.baseline_file, load_json_recover, atomic_write_json,
            {"common/수집/이미지캐시/x.webp": old_bytes})
        ledger = merge_plan.load_baseline(
            self.baseline_file, load_json_recover)
        entry = ledger["files"]["common/수집/이미지캐시/x.webp"]
        self.assertIsNone(entry["value"])
        # 내보내기: baseline/ 동봉 없이 해시만 manifest에 실린다
        exported = export_user_backup(self.paths, self.operations(), {})
        with zipfile.ZipFile(io.BytesIO(exported)) as archive:
            self.assertNotIn(
                "baseline/common/수집/이미지캐시/x.webp",
                archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
        declared = {item["path"]: item for item in manifest["files"]}
        image_entry = declared["common/수집/이미지캐시/x.webp"]
        self.assertEqual(
            image_entry["base_sha256"],
            hashlib.sha256(old_bytes).hexdigest())
        self.assertNotIn("base_size", image_entry)
        # 현재가 기준 그대로면 들어오는 쪽을 받는 판정
        blob = self.make_backup(
            {"common/수집/이미지캐시/x.webp": b"NEWIMAGEBYTES"},
            baselines={"common/수집/이미지캐시/x.webp": None},
        )
        # base_sha256이 실제 기준 해시가 되도록 다시 조립
        blob = self._rewrite_binary_base(
            blob, "common/수집/이미지캐시/x.webp",
            hashlib.sha256(old_bytes).hexdigest())
        _m, _p, _sha, plans, _c, _t, _f = backup_diff_plan(
            self.paths, self.operations(), blob)
        self.assertEqual(plans[0]["decision"], "take-incoming")
        self.assertFalse(plans[0]["json"])

    def _rewrite_binary_base(
        self, blob: bytes, logical: str, base_sha: str,
    ) -> bytes:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            data = {
                name: archive.read(name)
                for name in archive.namelist()
                if name != "manifest.json"
            }
        for entry in manifest["files"]:
            if entry["path"] == logical:
                entry["base_sha256"] = base_sha
                entry.pop("base_size", None)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
            for name, raw in data.items():
                archive.writestr(name, raw)
        return output.getvalue()

    def test_corrupt_embedded_baseline_degrades_to_two_way(self):
        (self.root / "규격.json").write_text(json.dumps({"a": 1}), "utf-8")
        base_raw = json.dumps({"a": 0}).encode("utf-8")
        blob = self.make_backup(
            {"common/규격.json": json.dumps({"a": 2}).encode("utf-8")},
            baselines={"common/규격.json": base_raw},
        )
        # 동봉 기준값을 손상시킨다 (해시 불일치)
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            manifest_raw = archive.read("manifest.json")
            data = {
                name: archive.read(name)
                for name in archive.namelist()
                if name != "manifest.json"
            }
        data["baseline/common/규격.json"] = b"corrupted"
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("manifest.json", manifest_raw)
            for name, raw in data.items():
                archive.writestr(name, raw)
        preview = preview_user_backup(
            self.paths, self.operations(), output.getvalue())
        self.assertEqual(preview["changes"][0]["decision"], "no-base")


if __name__ == "__main__":
    unittest.main()
