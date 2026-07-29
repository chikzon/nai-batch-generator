# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import unittest

from src.nai_studio.domain.variations import (
    accept_variation,
    canonical_character_asset,
    fingerprint_character_asset,
    plan_character_variation,
)


class CharacterVariationContractTests(unittest.TestCase):
    def asset(self):
        return {
            "name": "Alice",
            "appearance": "1girl, red hair, " + ("long prompt, " * 600),
            "outfit": "white dress",
            "negative": "bad hands",
            "variant": {"group": "dress", "id": "original"},
            "representative_image": {"path": "images/alice.webp"},
            "evidence_images": [{"url": "https://example.invalid/proof.webp"}],
            "variation_images": ["local:variation.webp"],
            "references": {
                "c1": {
                    "ref": {"id": "c1:alice"},
                    "strength": 1.2,
                    "fidelity": 0.7,
                },
                "character_reference": {
                    "ref": "local:alice.ref.png",
                    "strength": -0.5,
                    "fidelity": 2.0,
                },
                "reference_inset": {
                    "ref": {"content_hash": "abc"},
                    "strength": 0.8,
                    "fidelity": 0.6,
                },
            },
            "vibe_refs": [{
                "ref": "vibe:alice",
                "strength": 0.75,
                "info_extracted": 0.9,
            }],
            "random_pools": {
                "appearance": ["red hair", "pink hair"],
                "outfit": ["white dress", "black jacket"],
            },
            "temporary_generation_overrides": {
                "cfg_scale": 5.2,
                "sampler": "k_euler",
            },
            "lineage": [{"kind": "import", "source": "image:1"}],
            "future": {"must": ["stay"]},
        }

    def test_asset_preserves_all_character_image_reference_and_future_fields(self):
        raw = self.asset()
        before = copy.deepcopy(raw)
        first = canonical_character_asset(raw)
        second = canonical_character_asset(copy.deepcopy(raw))
        self.assertEqual(raw, before)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(first["appearance"], raw["appearance"])
        self.assertEqual(first["variant"]["id"], "original")
        self.assertEqual(first["references"]["character_reference"]["strength"], -0.5)
        self.assertEqual(first["references"]["reference_inset"]["fidelity"], 0.6)
        self.assertEqual(first["vibe_refs"][0]["fidelity"], 0.9)
        self.assertEqual(first["random_pools"]["outfit"], ["white dress", "black jacket"])
        self.assertEqual(first["future"], {"must": ["stay"]})
        self.assertEqual(fingerprint_character_asset(raw), first["fingerprint"])

    def test_character_reference_plan_is_pure_stable_and_uses_temporary_overrides(self):
        asset = self.asset()
        request = {
            "mode": "character-reference",
            "source_image": {"path": "input/alice.webp"},
            "reference": {"id": "ref:new"},
            "inset": {"path": "input/inset.webp"},
            "prompt_overrides": {
                "outfit": "blue dress",
                "negative": "lowres",
            },
            "seed": 123,
            "resolution": {"width": 832, "height": 1216},
            "temporary_settings": {"cfg_scale": 6.0, "scheduler": "karras"},
            "future_plan_field": {"kept": True},
        }
        before_asset, before_request = copy.deepcopy(asset), copy.deepcopy(request)
        first = plan_character_variation(asset, request)
        second = plan_character_variation(copy.deepcopy(asset), copy.deepcopy(request))
        self.assertEqual(asset, before_asset)
        self.assertEqual(request, before_request)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(first["temporary_settings"]["cfg_scale"], 6.0)
        self.assertEqual(first["temporary_settings"]["sampler"], "k_euler")
        self.assertEqual(first["resolution"], {"width": 832, "height": 1216})
        self.assertEqual(first["future_plan_field"], {"kept": True})

    def test_inpaint_and_img2img_keep_distinct_mode_contracts(self):
        asset = self.asset()
        inpaint = plan_character_variation(asset, {
            "mode": "inpaint",
            "source_image": "local:source.webp",
            "mask": {"path": "mask.png"},
        })
        img2img = plan_character_variation(asset, {
            "mode": "img2img",
            "source_image": "local:source.webp",
            "temporary_settings": {"strength": 0.45},
        })
        self.assertEqual(inpaint["mask"], {"path": "mask.png"})
        self.assertIsNone(img2img["mask"])
        self.assertNotEqual(inpaint["id"], img2img["id"])

    def test_accept_returns_proposals_without_mutating_or_overwriting_asset(self):
        asset = self.asset()
        plan = {
            "mode": "img2img",
            "source_image": "local:source.webp",
            "prompt_overrides": {
                "appearance": "1girl, pink hair",
                "outfit": "",
            },
            "seed": 9,
        }
        generated = {
            "image_ref": {"path": "output/pink.webp"},
            "metadata": {"seed": 9, "prompt": "1girl, pink hair"},
            "future_result": "kept",
        }
        before_asset = copy.deepcopy(asset)
        proposal = accept_variation(asset, plan, generated)
        self.assertEqual(asset, before_asset)
        self.assertEqual(proposal["action"], "proposal-only")
        self.assertEqual(proposal["evidence"]["status"], "proposed")
        self.assertEqual(proposal["variant"]["appearance"], "1girl, pink hair")
        self.assertEqual(proposal["variant"]["outfit"], "")
        self.assertEqual(
            proposal["variant"]["lineage"]["character_asset_id"],
            canonical_character_asset(asset)["id"],
        )
        self.assertEqual(proposal["generated"]["future_result"], "kept")
        self.assertEqual(len(asset["variation_images"]), 1)

    def test_invalid_reference_strength_mode_mask_seed_and_resolution_are_rejected(self):
        invalid_strength = self.asset()
        invalid_strength["references"]["c1"]["strength"] = 2.1
        with self.assertRaises(ValueError):
            canonical_character_asset(invalid_strength)

        invalid_ref = self.asset()
        invalid_ref["references"]["c1"]["ref"] = {"unknown": "value"}
        with self.assertRaises(ValueError):
            canonical_character_asset(invalid_ref)

        with self.assertRaises(ValueError):
            plan_character_variation(self.asset(), {"mode": "other"})
        with self.assertRaises(ValueError):
            plan_character_variation(self.asset(), {
                "mode": "inpaint",
                "source_image": "source.webp",
            })
        with self.assertRaises(ValueError):
            plan_character_variation(self.asset(), {
                "mode": "img2img",
                "source_image": "source.webp",
                "seed": -1,
            })
        with self.assertRaises(ValueError):
            plan_character_variation(self.asset(), {
                "mode": "img2img",
                "source_image": "source.webp",
                "resolution": {"width": 32, "height": 512},
            })
        with self.assertRaises(TypeError):
            plan_character_variation(self.asset(), {
                "mode": "img2img",
                "source_image": 123,
            })
        with self.assertRaises(ValueError):
            accept_variation(
                self.asset(),
                {
                    "mode": "img2img",
                    "source_image": "source.webp",
                    "character_asset_id": "character:other",
                },
                {"image_ref": "result.webp"},
            )


if __name__ == "__main__":
    unittest.main()
