# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
import unittest

from src.nai_studio.domain.evidence import (
    EVIDENCE_KINDS,
    EVIDENCE_SCHEMA,
    canonical_evidence,
    evidence_id,
    fingerprint_evidence,
)
from src.nai_studio.domain.knowledge import (
    KNOWLEDGE_KINDS,
    KNOWLEDGE_LIFECYCLES,
    KNOWLEDGE_SCHEMA,
    canonical_knowledge_asset,
    fingerprint_knowledge_asset,
    knowledge_asset_id,
)


LONG_PROMPT = (
    "1.2::masterpiece, very aesthetic::, (nier:automata), ||red||, "
    "{morning|night}, <character>, 한글, 😀, \"quote\", C:\\reference\n"
) * 80


class EvidenceContractTests(unittest.TestCase):
    def sample(self, kind="generation-record"):
        return {
            "kind": kind,
            "image": {
                "uri": "local:012345.webp",
                "sha256": "012345",
                "width": 832,
                "height": 1216,
            },
            "source": {
                "url": "https://example.invalid/post/12",
                "original_image_url": "https://example.invalid/image.webp",
            },
            "raw_metadata": {
                "Comment": json.dumps(
                    {"prompt": LONG_PROMPT, "uc": LONG_PROMPT[::-1]},
                    ensure_ascii=False,
                ),
            },
            "actual_generation": {
                "base": LONG_PROMPT,
                "negative": LONG_PROMPT[::-1],
                "seed": 123456,
                "characters": [
                    {"prompt": "1girl, white dress", "negative": "bad hands"},
                ],
            },
            "evaluation": {
                "seed_locked": True,
                "conditions": {"width": 832, "height": 1216},
                "rating": 4,
            },
        }

    def test_all_evidence_kinds_have_canonical_schema_and_stable_identity(self):
        for kind in EVIDENCE_KINDS:
            with self.subTest(kind=kind):
                record = canonical_evidence(self.sample(kind))
                self.assertEqual(record["schema"], EVIDENCE_SCHEMA)
                self.assertEqual(record["kind"], kind)
                self.assertEqual(record["id"], evidence_id(record))
                self.assertEqual(
                    record["fingerprint"],
                    fingerprint_evidence(record),
                )
                self.assertTrue(record["id"].startswith(f"evidence:{kind}:"))

    def test_prompt_metadata_generation_and_evaluation_are_lossless(self):
        source = self.sample()
        before = copy.deepcopy(source)
        record = canonical_evidence(source)

        self.assertEqual(source, before)
        self.assertEqual(record["actual_generation"]["base"], LONG_PROMPT)
        self.assertEqual(
            record["actual_generation"]["negative"],
            LONG_PROMPT[::-1],
        )
        self.assertEqual(
            record["raw_metadata"]["Comment"],
            source["raw_metadata"]["Comment"],
        )
        self.assertEqual(record["evaluation"], source["evaluation"])

    def test_identity_ignores_import_clock_and_json_key_order(self):
        first = self.sample()
        first["imported_at"] = "2026-07-29T01:00:00+09:00"
        second = {
            "evaluation": copy.deepcopy(first["evaluation"]),
            "actual_generation": copy.deepcopy(first["actual_generation"]),
            "raw_metadata": copy.deepcopy(first["raw_metadata"]),
            "source": copy.deepcopy(first["source"]),
            "image": copy.deepcopy(first["image"]),
            "kind": first["kind"],
            "imported_at": "2030-01-01T00:00:00Z",
        }
        self.assertEqual(evidence_id(first), evidence_id(second))
        self.assertEqual(
            fingerprint_evidence(first),
            fingerprint_evidence(second),
        )

    def test_content_change_changes_identity_and_future_fields_survive(self):
        first = self.sample()
        second = copy.deepcopy(first)
        second["actual_generation"]["seed"] += 1
        first["capture"] = {"article_revision": "abc", "extra": [1, 2, 3]}

        record = canonical_evidence(first)
        self.assertEqual(record["capture"], first["capture"])
        self.assertNotEqual(evidence_id(first), evidence_id(second))

    def test_invalid_kind_and_non_mapping_sections_are_rejected(self):
        with self.assertRaises(ValueError):
            canonical_evidence({"kind": "unknown"})
        with self.assertRaises(TypeError):
            canonical_evidence({
                "kind": "style",
                "image": "must not be silently discarded",
            })


class KnowledgeContractTests(unittest.TestCase):
    def evidence_ref(self):
        return canonical_evidence({
            "kind": "style",
            "image": {"sha256": "abc"},
            "source": {"url": "https://example.invalid/style"},
            "raw_metadata": {"prompt": LONG_PROMPT},
            "actual_generation": {"base": LONG_PROMPT},
            "evaluation": {"seed": 42},
        })["id"]

    def test_all_knowledge_kinds_have_explicit_content_contract(self):
        expected = {
            "style": {"base", "negative", "generation_settings"},
            "character": {
                "prompt", "negative", "variants",
                "reference_refs", "vibe_refs",
            },
            "artist": {"prompt", "ratings", "weight", "combinations"},
            "fragment": {"prompt", "selection"},
            "recipe": {"blueprint", "components"},
            "setting-material": {
                "scenes", "relationships", "positions", "options",
            },
        }
        for kind in KNOWLEDGE_KINDS:
            with self.subTest(kind=kind):
                asset = canonical_knowledge_asset({"kind": kind})
                self.assertEqual(asset["schema"], KNOWLEDGE_SCHEMA)
                self.assertEqual(asset["lifecycle"], "candidate")
                self.assertEqual(set(asset["content"]), expected[kind])
                self.assertTrue(asset["id"].startswith(f"knowledge:{kind}:"))

    def test_style_keeps_base_negative_settings_and_evidence_as_one_asset(self):
        source = {
            "kind": "style",
            "name": "무손실 그림체",
            "lifecycle": "confirmed",
            "evidence_refs": [self.evidence_ref()],
            "content": {
                "base": LONG_PROMPT,
                "negative": LONG_PROMPT[::-1],
                "generation_settings": {
                    "model": "nai-diffusion-4-5-full",
                    "cfg_scale": 5.7,
                    "seed": 123,
                },
            },
        }
        asset = canonical_knowledge_asset(source)
        self.assertEqual(asset["content"], source["content"])
        self.assertEqual(asset["evidence_refs"], source["evidence_refs"])

    def test_character_keeps_full_prompts_variants_and_reference_vibe_refs(self):
        content = {
            "prompt": LONG_PROMPT,
            "negative": LONG_PROMPT[::-1],
            "variants": [
                {
                    "id": "winter",
                    "prompt": "white coat, red scarf",
                    "negative": "summer clothes",
                },
            ],
            "reference_refs": ["reference:character:one"],
            "vibe_refs": ["vibe:character:one"],
        }
        asset = canonical_knowledge_asset({
            "kind": "character",
            "content": content,
        })
        self.assertEqual(asset["content"], content)

    def test_lifecycle_changes_do_not_change_content_identity(self):
        base = {
            "kind": "fragment",
            "name": "배경 조각",
            "content": {
                "prompt": LONG_PROMPT,
                "selection": {"mode": "sequential"},
            },
        }
        ids = set()
        fingerprints = set()
        for lifecycle in KNOWLEDGE_LIFECYCLES:
            item = copy.deepcopy(base)
            item["lifecycle"] = lifecycle
            ids.add(knowledge_asset_id(item))
            fingerprints.add(fingerprint_knowledge_asset(item))
        self.assertEqual(len(ids), 1)
        self.assertEqual(len(fingerprints), 1)

    def test_content_or_evidence_change_changes_asset_identity(self):
        base = {
            "kind": "artist",
            "evidence_refs": [self.evidence_ref()],
            "content": {
                "prompt": "artist:name",
                "ratings": [4, 5],
                "weight": 1.2,
                "combinations": ["artist:other"],
            },
        }
        changed = copy.deepcopy(base)
        changed["content"]["weight"] = 1.3
        changed_evidence = copy.deepcopy(base)
        changed_evidence["evidence_refs"].append("evidence:style:other")
        self.assertNotEqual(
            knowledge_asset_id(base),
            knowledge_asset_id(changed),
        )
        self.assertNotEqual(
            knowledge_asset_id(base),
            knowledge_asset_id(changed_evidence),
        )

    def test_future_fields_survive_and_input_is_not_modified(self):
        source = {
            "kind": "recipe",
            "lifecycle": "shared",
            "content": {
                "blueprint": {"schema": "nai-generation-blueprint/v1"},
                "components": ["style:one", "character:one"],
                "future_resolution": {"priority": ["style", "setting"]},
            },
            "lineage": {"parent": "knowledge:recipe:old"},
        }
        before = copy.deepcopy(source)
        asset = canonical_knowledge_asset(source)
        self.assertEqual(source, before)
        self.assertEqual(
            asset["content"]["future_resolution"],
            source["content"]["future_resolution"],
        )
        self.assertEqual(asset["lineage"], source["lineage"])

    def test_invalid_kind_lifecycle_or_refs_are_rejected(self):
        with self.assertRaises(ValueError):
            canonical_knowledge_asset({"kind": "preset"})
        with self.assertRaises(ValueError):
            canonical_knowledge_asset({
                "kind": "style",
                "lifecycle": "published",
            })
        with self.assertRaises(TypeError):
            canonical_knowledge_asset({
                "kind": "character",
                "evidence_refs": "must remain a list",
            })


if __name__ == "__main__":
    unittest.main()
