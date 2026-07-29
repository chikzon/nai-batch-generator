# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
import unittest

from src.nai_studio.domain.resources import (
    RESOURCE_BUNDLE_SCHEMA,
    RESOURCE_SCHEMA,
    canonical_resource,
    export_resource_document,
    fingerprint_resource,
    merge_resources,
    parse_resource_document,
)


LONG_ENCODED = "YWJjZGVmMDEyMzQ1Njc4OQ==" * 3500


class ResourceContractTests(unittest.TestCase):
    def vibe(self):
        return {
            "kind": "vibe",
            "name": "긴 인코딩 바이브",
            "image_ref": {},
            "encoded": LONG_ENCODED,
            "model": "nai-diffusion-4-5-full",
            "strength": 0.65,
            "information_extracted": 0.7,
            "ref_type": "vibe",
            "source": {
                "url": "https://example.invalid/post/1",
                "path": r"C:\private\source.webp",
                "token": "must-not-export",
            },
            "source_refs": ["source:post:1"],
            "evidence_refs": ["evidence:style:1"],
            "future_field": {"profile": "v4"},
        }

    def character_reference(self):
        return {
            "kind": "character-reference",
            "name": "캐릭터 참조",
            "image_ref": {
                "content_sha256": "abc123",
                "uri": "local:abc123.webp",
            },
            "model": "nai-diffusion-4-5-full",
            "strength": 1.2,
            "information_extracted": 1.0,
            "fidelity": 0.8,
            "ref_type": "character&style",
            "source_refs": ["source:character:1"],
            "evidence_refs": ["evidence:character:1"],
        }

    def test_canonical_resources_preserve_encoded_settings_refs_and_future_fields(self):
        source = self.vibe()
        before = copy.deepcopy(source)
        vibe = canonical_resource(source)
        cref = canonical_resource(self.character_reference())

        self.assertEqual(source, before)
        self.assertEqual(vibe["schema"], RESOURCE_SCHEMA)
        self.assertEqual(vibe["encoded"], LONG_ENCODED)
        self.assertIn("information_extracted", vibe["locked_fields"])
        self.assertEqual(vibe["future_field"], {"profile": "v4"})
        self.assertEqual(cref["kind"], "character-reference")
        self.assertEqual(cref["strength"], 1.2)
        self.assertEqual(cref["fidelity"], 0.8)
        self.assertEqual(cref["ref_type"], "character&style")

    def test_content_fingerprint_ignores_usage_settings_and_source_paths(self):
        first = self.vibe()
        second = copy.deepcopy(first)
        second["strength"] = -0.5
        second["information_extracted"] = 1.5
        second["name"] = "다른 표시 이름"
        second["ref_type"] = "style"
        second["source"]["path"] = r"D:\other\copy.webp"
        second["source_refs"] = ["source:post:2"]
        self.assertEqual(
            fingerprint_resource(first),
            fingerprint_resource(second),
        )

    def test_parse_naiv4vibe_aliases_and_encoded_model_bundle(self):
        single = {
            "identifier": "novelai-vibe-transfer",
            "model": "nai-diffusion-4-full",
            "encoding": LONG_ENCODED,
            "informationExtracted": 0.8,
            "strength": 0.6,
        }
        parsed = parse_resource_document(
            json.dumps(single).encode("utf-8"),
            "sample.naiv4vibe",
        )
        self.assertEqual(parsed["source_format"], "naiv4vibe")
        self.assertEqual(parsed["resources"][0]["encoded"], LONG_ENCODED)
        self.assertEqual(
            parsed["resources"][0]["information_extracted"],
            0.8,
        )

        official_bundle = {
            "identifier": "novelai-vibe-bundle",
            "encodings": {
                "nai-diffusion-4-full": LONG_ENCODED,
                "nai-diffusion-4-5-full": {
                    "encodedVibe": LONG_ENCODED[::-1],
                    "infoExtracted": 0.9,
                    "strength": 0.5,
                },
            },
        }
        bundle = parse_resource_document(
            json.dumps(official_bundle),
            "two.naiv4vibebundle",
        )
        self.assertEqual(bundle["source_format"], "naiv4vibebundle")
        self.assertEqual(len(bundle["resources"]), 2)
        self.assertEqual(
            {item["model"] for item in bundle["resources"]},
            {"nai-diffusion-4-full", "nai-diffusion-4-5-full"},
        )

    def test_bundle_export_roundtrip_keeps_content_without_token_or_local_path(self):
        resources = [self.vibe(), self.character_reference()]
        before = copy.deepcopy(resources)
        exported = export_resource_document(resources, bundle=True)
        text = exported.decode("utf-8")

        self.assertEqual(resources, before)
        self.assertNotIn("must-not-export", text)
        self.assertNotIn(r"C:\\private\\source.webp", text)
        document = json.loads(text)
        self.assertEqual(document["schema"], RESOURCE_BUNDLE_SCHEMA)
        parsed = parse_resource_document(exported, "bundle.json")
        self.assertEqual(len(parsed["resources"]), 2)
        self.assertEqual(parsed["resources"][0]["encoded"], LONG_ENCODED)
        self.assertEqual(
            [item["fingerprint"] for item in parsed["resources"]],
            [
                canonical_resource(item)["fingerprint"]
                for item in resources
            ],
        )

    def test_single_export_roundtrip(self):
        exported = export_resource_document([self.vibe()], bundle=False)
        parsed = parse_resource_document(exported, "one.json")
        self.assertEqual(len(parsed["resources"]), 1)
        self.assertEqual(parsed["resources"][0]["encoded"], LONG_ENCODED)

    def test_merge_same_content_keeps_sources_evidence_and_reports_settings_conflicts(self):
        first = self.vibe()
        second = copy.deepcopy(first)
        second["strength"] = 1.4
        second["information_extracted"] = 0.9
        second["source"] = {"url": "https://example.invalid/post/2"}
        second["source_refs"] = ["source:post:2"]
        second["evidence_refs"] = ["evidence:style:2"]
        first_before = copy.deepcopy(first)
        second_before = copy.deepcopy(second)
        result = merge_resources(first, second)
        merged = result["resources"][0]

        self.assertEqual(first, first_before)
        self.assertEqual(second, second_before)
        self.assertEqual(len(result["resources"]), 1)
        self.assertEqual(
            merged["source_refs"],
            ["source:post:1", "source:post:2"],
        )
        self.assertEqual(
            merged["evidence_refs"],
            ["evidence:style:1", "evidence:style:2"],
        )
        self.assertEqual(len(merged["sources"]), 2)
        paths = {item["path"] for item in result["conflicts"]}
        self.assertEqual(paths, {"strength", "information_extracted"})

    def test_invalid_ranges_and_unknown_documents_are_rejected(self):
        for field in ("strength", "information_extracted", "fidelity"):
            for value in (-1.01, 2.01):
                with self.subTest(field=field, value=value):
                    resource = self.character_reference()
                    resource[field] = value
                    with self.assertRaises(ValueError):
                        canonical_resource(resource)
        with self.assertRaises(ValueError):
            parse_resource_document('{"hello":"world"}', "unknown.json")
        with self.assertRaises(ValueError):
            parse_resource_document(b"\xff\xfe", "bad.naiv4vibe")


if __name__ == "__main__":
    unittest.main()
