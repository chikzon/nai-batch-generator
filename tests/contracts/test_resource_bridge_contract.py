# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import copy
import json
import unittest

from src.nai_studio.domain.resources import parse_resource_document
from src.nai_studio.services.resource_bridge import (
    LEGACY_IMPORT_PLAN_SCHEMA,
    export_legacy_resources,
    legacy_resource_import_plan,
    project_legacy_resources,
)


LONG_ENCODED = "QUJDREVGR0hJSktMTU5PUA==" * 4000
IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" + b"test-image" * 40


class ResourceBridgeContractTests(unittest.TestCase):
    def config(self):
        return {
            "model": "nai-diffusion-4-5-full",
            "token": "must-never-cross-export",
            "vibes": [
                {
                    "id": "vibe-old",
                    "name": "기존 바이브",
                    "enabled": True,
                    "strength": 0.75,
                    "info_extracted": 0.8,
                    "encoded_ie": 0.8,
                    "evidence_refs": ["evidence:style:one"],
                },
            ],
            "char_refs": [
                {
                    "id": "ref-old",
                    "name": "기존 레퍼런스",
                    "enabled": False,
                    "ref_type": "character",
                    "strength": 1.2,
                    "fidelity": 0.65,
                },
            ],
            "characters": [
                {
                    "id": "character:one",
                    "name": "주인공",
                    "vibe_ids": ["vibe-old"],
                    "reference_ids": ["ref-old"],
                },
            ],
        }

    def file_index(self):
        return {
            "vibe-old.png": {
                "content_sha256": "image-one",
                "uri": "local:image-one.webp",
                "absolute_path": r"C:\private\vibe-old.png",
            },
            "vibe-old.vibe": LONG_ENCODED,
            "ref-old.ref.png": IMAGE_BYTES,
        }

    def test_projects_actual_legacy_fields_and_files_without_mutating_inputs(self):
        cfg = self.config()
        files = self.file_index()
        cfg_before = copy.deepcopy(cfg)
        files_before = copy.deepcopy(files)
        result = project_legacy_resources(cfg, file_index=files)

        self.assertEqual(cfg, cfg_before)
        self.assertEqual(files, files_before)
        self.assertEqual(len(result["resources"]), 2)
        vibe, reference = result["resources"]
        self.assertEqual(vibe["kind"], "vibe")
        self.assertEqual(vibe["encoded"], LONG_ENCODED)
        self.assertEqual(vibe["information_extracted"], 0.8)
        self.assertNotIn("absolute_path", vibe["image_ref"])
        self.assertEqual(reference["kind"], "character-reference")
        self.assertEqual(reference["ref_type"], "character")
        self.assertEqual(reference["strength"], 1.2)
        self.assertEqual(reference["fidelity"], 0.65)

        character = result["bindings"]["characters"][0]
        self.assertEqual(character["vibe_refs"], [vibe["id"]])
        self.assertEqual(
            character["character_reference_refs"],
            [reference["id"]],
        )
        self.assertEqual(character["missing_legacy_ids"], [])

    def test_stale_encoding_preserves_actual_ie_and_reports_requested_difference(self):
        cfg = self.config()
        cfg["vibes"][0]["info_extracted"] = 1.1
        result = project_legacy_resources(cfg, file_index=self.file_index())
        vibe = result["resources"][0]

        self.assertEqual(vibe["information_extracted"], 0.8)
        self.assertEqual(vibe["requested_information_extracted"], 1.1)
        issue = next(
            item for item in result["issues"]
            if item["code"] == "stale-vibe-encoding"
        )
        self.assertTrue(issue["can_reencode"])

    def test_export_is_canonical_pathless_tokenless_and_encoded_is_uncut(self):
        exported = export_legacy_resources(
            self.config(),
            file_index=self.file_index(),
        )
        text = exported.decode("utf-8")
        self.assertNotIn("must-never-cross-export", text)
        self.assertNotIn(r"C:\\private", text)
        parsed = parse_resource_document(exported, "legacy-bundle.json")
        self.assertEqual(parsed["resources"][0]["encoded"], LONG_ENCODED)
        imported = legacy_resource_import_plan(
            exported,
            filename="legacy-bundle.json",
            existing_config={"model": "nai-diffusion-4-5-full"},
        )
        self.assertEqual(len(imported["additions"]["vibes"]), 1)
        self.assertEqual(len(imported["additions"]["char_refs"]), 1)
        self.assertEqual(
            {write["kind"] for write in imported["writes"]},
            {"text", "binary"},
        )

    def test_naiv4vibe_import_plan_uses_existing_fields_and_does_not_apply(self):
        document = {
            "identifier": "novelai-vibe-transfer",
            "model": "nai-diffusion-4-5-full",
            "encoding": LONG_ENCODED,
            "informationExtracted": 0.85,
            "strength": 0.55,
            "name": "가져온 바이브",
            "token": "must-not-enter-plan",
            "path": r"C:\private\source.naiv4vibe",
        }
        existing = self.config()
        before = copy.deepcopy(existing)
        plan = legacy_resource_import_plan(
            json.dumps(document),
            filename="sample.naiv4vibe",
            existing_config=existing,
        )

        self.assertEqual(existing, before)
        self.assertEqual(plan["schema"], LEGACY_IMPORT_PLAN_SCHEMA)
        self.assertFalse(plan["applied"])
        self.assertEqual(len(plan["additions"]["vibes"]), 1)
        item = plan["additions"]["vibes"][0]
        self.assertFalse(item["enabled"])
        self.assertEqual(item["strength"], 0.55)
        self.assertEqual(item["info_extracted"], 0.85)
        self.assertEqual(item["encoded_ie"], 0.85)
        write = plan["writes"][0]
        self.assertTrue(write["filename"].endswith(".vibe"))
        self.assertEqual(write["content"], LONG_ENCODED)
        self.assertNotIn("token", repr(plan).lower())
        self.assertNotIn(r"C:\private", repr(plan))

    def test_bundle_import_only_accepts_matching_model_and_materializable_refs(self):
        embedded = base64.b64encode(IMAGE_BYTES).decode("ascii")
        bundle = {
            "schema": "nai-resource-bundle/v1",
            "resources": [
                {
                    "kind": "vibe",
                    "name": "맞는 모델",
                    "encoded": LONG_ENCODED,
                    "model": "nai-diffusion-4-5-full",
                    "strength": 0.6,
                    "information_extracted": 0.7,
                },
                {
                    "kind": "vibe",
                    "name": "다른 모델",
                    "encoded": LONG_ENCODED[::-1],
                    "model": "nai-diffusion-4-full",
                    "strength": 0.6,
                    "information_extracted": 0.7,
                },
                {
                    "kind": "character-reference",
                    "name": "포함된 이미지",
                    "image_ref": {
                        "data_base64": embedded,
                        "content_sha256": "image-ref",
                    },
                    "model": "nai-diffusion-4-5-full",
                    "strength": 1.0,
                    "information_extracted": 1.0,
                    "fidelity": 0.7,
                    "ref_type": "character&style",
                },
                {
                    "kind": "character-reference",
                    "name": "경로뿐인 이미지",
                    "image_ref": {"uri": "local:missing.webp"},
                    "strength": 1.0,
                    "information_extracted": 1.0,
                    "fidelity": 0.7,
                    "ref_type": "character",
                },
            ],
        }
        plan = legacy_resource_import_plan(
            bundle,
            existing_config={"model": "nai-diffusion-4-5-full"},
        )
        self.assertEqual(len(plan["additions"]["vibes"]), 1)
        self.assertEqual(len(plan["additions"]["char_refs"]), 1)
        self.assertEqual(
            {item["reason"] for item in plan["skipped"]},
            {
                "model-mismatch",
                "character-reference-requires-embedded-image",
            },
        )
        self.assertEqual(
            {write["kind"] for write in plan["writes"]},
            {"text", "binary"},
        )

    def test_existing_resource_fingerprint_is_skipped_without_writes(self):
        document = {
            "identifier": "novelai-vibe-transfer",
            "model": "nai-diffusion-4-5-full",
            "encoding": LONG_ENCODED,
            "informationExtracted": 0.7,
            "strength": 0.6,
        }
        first = legacy_resource_import_plan(
            document,
            existing_config={"model": "nai-diffusion-4-5-full"},
        )
        fingerprint = first["additions"]["vibes"][0][
            "resource_fingerprint"
        ]
        second = legacy_resource_import_plan(
            document,
            existing_config={
                "model": "nai-diffusion-4-5-full",
                "vibes": [{"id": "old", "resource_fingerprint": fingerprint}],
            },
        )
        self.assertEqual(second["additions"]["vibes"], [])
        self.assertEqual(second["writes"], [])
        self.assertEqual(second["skipped"][0]["reason"], "already-imported")

    def test_duplicate_resource_inside_one_document_is_only_planned_once(self):
        row = {
            "kind": "vibe",
            "encoded": LONG_ENCODED,
            "model": "nai-diffusion-4-5-full",
            "strength": 0.6,
            "information_extracted": 0.7,
        }
        plan = legacy_resource_import_plan(
            {
                "schema": "nai-resource-bundle/v1",
                "resources": [row, copy.deepcopy(row)],
            },
            existing_config={"model": "nai-diffusion-4-5-full"},
        )
        self.assertEqual(len(plan["additions"]["vibes"]), 1)
        self.assertEqual(len(plan["writes"]), 1)
        self.assertEqual(plan["skipped"][0]["reason"], "already-imported")


if __name__ == "__main__":
    unittest.main()
