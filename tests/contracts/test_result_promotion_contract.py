# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
import unittest

from src.nai_studio.services.evaluation_bridge import EVALUATION_EVENT_SCHEMA
from src.nai_studio.services.result_promotion import (
    PROMOTION_LEDGER_SCHEMA,
    RESULT_PROMOTION_SCHEMA,
    append_promotion_events,
    build_result_promotion,
    new_promotion_ledger,
)


TOKEN = "pst-ne-result-secret-that-must-not-be-saved"
ABSOLUTE_PATH = r"C:\Users\private\result.webp"
RAW_PAYLOAD = "raw-payload-private-body"
RESULT_PATH = "comparison/run/result.webp"


class ResultPromotionContractTests(unittest.TestCase):
    def result(self):
        return {
            "path": RESULT_PATH,
            "content_sha256": "a" * 64,
            "request_id": "req-result-one",
            "payload_hash": "b" * 64,
            "blueprint_fingerprint": "c" * 64,
            "raw_payload": {
                "token": TOKEN,
                "prompt": RAW_PAYLOAD,
            },
            "source_path": ABSOLUTE_PATH,
            "image_bytes": b"private image",
        }

    def manifest(self, *, folder="comparison/run"):
        return {
            "signature": "d" * 64,
            "folder": folder,
            "mode": "style_character",
            "completed": {
                "cell-one": {
                    "file": RESULT_PATH,
                    "style_id": "style:one",
                    "character_id": "character:one",
                    "seed": 1234,
                    "seed_index": 2,
                    "width": 832,
                    "height": 1216,
                    "raw_payload": RAW_PAYLOAD,
                    "token": TOKEN,
                },
            },
        }

    def evaluation(self):
        return {
            "subject": {
                "kind": "generation-result",
                "path": RESULT_PATH,
            },
            "favorite": True,
            "rating": 4.5,
            "memo": "손과 구도가 안정적",
            "tags": ["선명", "후보"],
            "review_state": "confirmed",
            "evidence_refs": ["evidence:generation-record:prior"],
            "result_refs": [f"result:{RESULT_PATH}"],
            "asset_refs": ["knowledge:style:source"],
            "comparison_lineage": {
                "manifest_index": 3,
                "job_key": "cell-one",
                "mode": "style_character",
            },
            "result_record": {
                "raw_payload": RAW_PAYLOAD,
                "token": TOKEN,
            },
        }

    def style_content(self):
        return {
            "base": "1.2::artist alpha::,\nartist beta",
            "negative": "bad hands,\nlowres",
            "generation_settings": {
                "model": "nai-diffusion-4-5-full",
                "cfg_scale": 5.5,
                "sampler": "k_euler_ancestral",
                "seed": 1234,
            },
        }

    def character_content(self):
        return {
            "prompt": "1girl,\nvery long silver hair",
            "negative": "extra fingers,\nwrong eye color",
            "variants": [
                {
                    "id": "winter",
                    "prompt": "white coat,\nblue scarf",
                    "negative": "summer clothes",
                },
            ],
            "reference_refs": ["reference:character:one"],
            "vibe_refs": ["vibe:character:one"],
        }

    def assert_no_runtime_secrets(self, value):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn(ABSOLUTE_PATH, text)
        self.assertNotIn(RAW_PAYLOAD, text)
        self.assertNotIn("image_bytes", text)
        self.assertNotIn("raw_payload", text)
        return text

    def test_style_keeps_explicit_bundle_and_full_result_lineage(self):
        content = self.style_content()
        result = build_result_promotion(
            self.result(),
            self.manifest(),
            self.evaluation(),
            target="style",
            content=content,
            name="검증 그림체",
        )
        self.assertEqual(result["schema"], RESULT_PROMOTION_SCHEMA)
        self.assertEqual(result["target"], "style")
        self.assertEqual(
            result["knowledge_asset"]["content"],
            content,
        )
        evidence = result["evidence"]
        self.assertEqual(evidence["image"], {
            "path": RESULT_PATH,
            "content_sha256": "a" * 64,
        })
        self.assertIsNone(evidence["raw_metadata"])
        self.assertEqual(evidence["actual_generation"], {})
        self.assertEqual(evidence["evaluation"]["rating"], 4.5)
        self.assertEqual(evidence["evaluation"]["memo"], "손과 구도가 안정적")
        self.assertEqual(evidence["evaluation"]["tags"], ["선명", "후보"])

        lineage = result["lineage"]
        self.assertEqual(lineage["source_result_ref"], f"result:{RESULT_PATH}")
        self.assertEqual(lineage["execution"], {
            "request_id": "req-result-one",
            "payload_hash": "b" * 64,
            "blueprint_fingerprint": "c" * 64,
        })
        self.assertEqual(lineage["comparison"]["job_key"], "cell-one")
        self.assertEqual(lineage["comparison"]["style_id"], "style:one")
        self.assertEqual(
            lineage["comparison"]["character_id"],
            "character:one",
        )
        self.assertEqual(lineage["comparison"]["seed"], 1234)
        self.assertEqual(lineage["evaluation"]["rating"], 4.5)
        self.assertEqual(result["knowledge_asset"]["lineage"], lineage)
        self.assertEqual(evidence["lineage"], lineage)
        self.assertEqual(
            result["knowledge_asset"]["evidence_refs"],
            [evidence["id"], "evidence:generation-record:prior"],
        )
        event = result["promotion_event"]
        self.assertEqual(event["schema"], EVALUATION_EVENT_SCHEMA)
        self.assertEqual(event["kind"], "promotion-proposed")
        self.assertFalse(event["payload"]["decision"]["automatic"])
        self.assertEqual(event["payload"]["decision"]["target"], "style")
        self.assert_no_runtime_secrets(result)

    def test_character_keeps_whole_prompt_variants_reference_and_vibe(self):
        content = self.character_content()
        before = copy.deepcopy(content)
        result = build_result_promotion(
            self.result(),
            self.manifest(),
            self.evaluation(),
            target="character",
            content=content,
            name="은발 캐릭터",
        )
        self.assertEqual(content, before)
        self.assertEqual(
            result["knowledge_asset"]["content"],
            content,
        )
        self.assertEqual(
            result["knowledge_asset"]["content"]["prompt"],
            "1girl,\nvery long silver hair",
        )
        self.assertEqual(
            result["knowledge_asset"]["content"]["variants"],
            content["variants"],
        )
        self.assertEqual(
            result["knowledge_asset"]["content"]["reference_refs"],
            ["reference:character:one"],
        )
        self.assertEqual(
            result["knowledge_asset"]["content"]["vibe_refs"],
            ["vibe:character:one"],
        )
        self.assert_no_runtime_secrets(result)

    def test_never_infers_missing_content_from_result_or_evaluation(self):
        result = self.result()
        result.update({
            "base": "must not be inferred",
            "negative": "must not be inferred",
            "generation_settings": {"cfg_scale": 7},
        })
        with self.assertRaises(ValueError):
            build_result_promotion(
                result,
                self.manifest(),
                self.evaluation(),
                target="style",
                content={"base": "", "negative": ""},
            )
        with self.assertRaises(ValueError):
            build_result_promotion(
                result,
                self.manifest(),
                self.evaluation(),
                target="character",
                content={
                    "prompt": "character",
                    "negative": "",
                    "variants": [],
                    "reference_refs": [],
                },
            )
        with self.assertRaises(ValueError):
            build_result_promotion(
                result,
                self.manifest(),
                self.evaluation(),
                target="reference",
                content={},
            )

    def test_rejects_secrets_absolute_paths_and_binary_in_explicit_content(self):
        unsafe_values = [
            {
                **self.style_content(),
                "api_token": TOKEN,
            },
            {
                **self.style_content(),
                "generation_settings": {
                    "output_path": ABSOLUTE_PATH,
                },
            },
            {
                **self.style_content(),
                "preview": b"image",
            },
        ]
        for content in unsafe_values:
            with self.subTest(content=list(content)):
                with self.assertRaises((TypeError, ValueError)):
                    build_result_promotion(
                        self.result(),
                        self.manifest(folder=ABSOLUTE_PATH),
                        self.evaluation(),
                        target="style",
                        content=content,
                    )
        character = self.character_content()
        character["reference_refs"] = [ABSOLUTE_PATH]
        with self.assertRaises(ValueError):
            build_result_promotion(
                self.result(),
                self.manifest(),
                self.evaluation(),
                target="character",
                content=character,
            )

    def test_removes_unsafe_optional_manifest_folder_but_keeps_lineage(self):
        result = build_result_promotion(
            self.result(),
            self.manifest(folder=ABSOLUTE_PATH),
            self.evaluation(),
            target="style",
            content=self.style_content(),
        )
        comparison = result["lineage"]["comparison"]
        self.assertEqual(comparison["manifest_folder"], "")
        self.assertEqual(comparison["manifest_signature"], "d" * 64)
        self.assertEqual(comparison["job_key"], "cell-one")
        self.assert_no_runtime_secrets(result)

    def test_rejects_invalid_result_identity_and_manifest_mismatch(self):
        bad_cases = []
        absolute = self.result()
        absolute["path"] = ABSOLUTE_PATH
        bad_cases.append((absolute, self.manifest(), self.evaluation()))
        traversal = self.result()
        traversal["path"] = "../outside.webp"
        bad_cases.append((traversal, self.manifest(), self.evaluation()))
        bad_sha = self.result()
        bad_sha["content_sha256"] = "not-a-sha"
        bad_cases.append((bad_sha, self.manifest(), self.evaluation()))
        bad_payload_hash = self.result()
        bad_payload_hash["payload_hash"] = "bad"
        bad_cases.append((
            bad_payload_hash,
            self.manifest(),
            self.evaluation(),
        ))
        for result, manifest, evaluation in bad_cases:
            with self.subTest(path=result.get("path")):
                with self.assertRaises(ValueError):
                    build_result_promotion(
                        result,
                        manifest,
                        evaluation,
                        target="style",
                        content=self.style_content(),
                    )

        mismatch_manifest = self.manifest()
        mismatch_manifest["completed"]["cell-one"]["file"] = "other.webp"
        with self.assertRaises(ValueError):
            build_result_promotion(
                self.result(),
                mismatch_manifest,
                self.evaluation(),
                target="style",
                content=self.style_content(),
            )
        mismatch_evaluation = self.evaluation()
        mismatch_evaluation["result_refs"] = ["result:other.webp"]
        with self.assertRaises(ValueError):
            build_result_promotion(
                self.result(),
                self.manifest(),
                mismatch_evaluation,
                target="style",
                content=self.style_content(),
            )

    def test_append_only_ledger_is_idempotent_and_inputs_are_immutable(self):
        style = build_result_promotion(
            self.result(),
            self.manifest(),
            self.evaluation(),
            target="style",
            content=self.style_content(),
        )
        ledger = new_promotion_ledger()
        before = copy.deepcopy((ledger, style))
        first = append_promotion_events(ledger, [style])
        self.assertEqual((ledger, style), before)
        self.assertEqual(first["ledger"]["schema"], PROMOTION_LEDGER_SCHEMA)
        self.assertEqual(first["appended"], [style["id"]])
        self.assertEqual(first["duplicates"], [])

        duplicate = append_promotion_events(first["ledger"], [style])
        self.assertEqual(len(duplicate["ledger"]["events"]), 1)
        self.assertEqual(duplicate["appended"], [])
        self.assertEqual(duplicate["duplicates"], [style["id"]])

        changed_content = self.style_content()
        changed_content["base"] += ", new explicit artist"
        changed = build_result_promotion(
            self.result(),
            self.manifest(),
            self.evaluation(),
            target="style",
            content=changed_content,
        )
        self.assertNotEqual(changed["id"], style["id"])
        final = append_promotion_events(duplicate["ledger"], [changed])
        self.assertEqual(len(final["ledger"]["events"]), 2)
        self.assertEqual(final["appended"], [changed["id"]])
        self.assert_no_runtime_secrets(final)

    def test_append_rejects_raw_metadata_or_raw_payload_in_forged_event(self):
        event = build_result_promotion(
            self.result(),
            self.manifest(),
            self.evaluation(),
            target="style",
            content=self.style_content(),
        )
        forged = copy.deepcopy(event)
        forged["evidence"]["raw_metadata"] = {"prompt": RAW_PAYLOAD}
        with self.assertRaises(ValueError):
            append_promotion_events(None, [forged])

        forged = copy.deepcopy(event)
        forged["knowledge_asset"]["content"]["raw_payload"] = RAW_PAYLOAD
        with self.assertRaises(ValueError):
            append_promotion_events(None, [forged])

        forged = copy.deepcopy(event)
        forged["evidence"]["image"]["path"] = ABSOLUTE_PATH
        with self.assertRaises(ValueError):
            append_promotion_events(None, [forged])

        forged = copy.deepcopy(event)
        forged["evidence"]["evaluation"]["memo"] = TOKEN
        with self.assertRaises(ValueError):
            append_promotion_events(None, [forged])


if __name__ == "__main__":
    unittest.main()
