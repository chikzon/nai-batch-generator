# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import unittest

from src.nai_studio.domain.variations import (
    accept_variation,
    plan_character_variation,
)
from src.nai_studio.services.variation_bridge import (
    approved_proposal_to_legacy_candidates,
    character_asset_from_legacy_record,
    character_assets_from_legacy_config,
    selected_variation_values,
    variation_plan_to_legacy_payload_material,
)


class VariationBridgeContractTests(unittest.TestCase):
    def config(self):
        return {
            "characters": [{
                "id": "alice",
                "name": "Alice",
                "female": "1girl, red hair, " + ("long prompt, " * 500),
                "clothed": "white dress",
                "negative": "bad hands",
                "variant": {"group": "dress", "id": "v1"},
                "reference_ids": ["ref-a", "missing-ref"],
                "vibe_ids": ["vibe-a"],
                "images": [{"path": "proof.webp"}],
                "future": {"must": "stay"},
            }],
            "char_slots": [{
                "id": "slot-bob",
                "name": "Bob",
                "prompt": "1boy, blue hair",
                "outfit": "black jacket",
                "negative": "bad anatomy",
                "reference_ids": [],
                "vibe_ids": [],
            }],
            "char_refs": [{
                "id": "ref-a",
                "name": "Alice ref",
                "strength": 1.2,
                "fidelity": 0.8,
                "ref_type": "character&style",
            }],
            "vibes": [{
                "id": "vibe-a",
                "name": "Alice vibe",
                "strength": 0.7,
                "info_extracted": 0.9,
            }],
        }

    def test_legacy_characters_slots_and_refs_project_without_mutation_or_loss(self):
        cfg = self.config()
        before = copy.deepcopy(cfg)
        assets = character_assets_from_legacy_config(cfg)
        self.assertEqual(cfg, before)
        self.assertEqual(len(assets), 2)
        alice, bob = assets
        self.assertEqual(alice["appearance"], cfg["characters"][0]["female"])
        self.assertEqual(alice["outfit"], "white dress")
        self.assertEqual(
            alice["references"]["character_reference"]["strength"], 1.2
        )
        self.assertEqual(
            [item["id"] for item in alice["legacy_reference_records"]],
            ["ref-a", "missing-ref"],
        )
        self.assertTrue(alice["legacy_reference_records"][1]["missing"])
        self.assertEqual(alice["vibe_refs"][0]["fidelity"], 0.9)
        self.assertEqual(
            alice["legacy_record"]["future"],
            {"must": "stay"},
        )
        self.assertEqual(bob["appearance"], "1boy, blue hair")
        self.assertEqual(bob["legacy_origin"], "char_slots")

    def test_img2img_and_inpaint_plans_become_existing_payload_material(self):
        asset = character_asset_from_legacy_record(
            self.config()["characters"][0],
            char_refs=self.config()["char_refs"],
            vibes=self.config()["vibes"],
        )
        request = {
            "mode": "img2img",
            "source_image": {"path": "source.webp"},
            "prompt_overrides": {"outfit": "blue dress"},
            "seed": 44,
            "resolution": {"width": 832, "height": 1216},
            "temporary_settings": {
                "strength": 0.75,
                "noise": 0.1,
                "cfg_scale": 6.0,
            },
        }
        before_asset, before_request = copy.deepcopy(asset), copy.deepcopy(request)
        img2img = variation_plan_to_legacy_payload_material(asset, request)
        self.assertEqual(asset, before_asset)
        self.assertEqual(request, before_request)
        self.assertEqual(img2img["action"], "img2img")
        self.assertEqual(img2img["char_slots"][0]["outfit"], "blue dress")
        self.assertEqual(img2img["char_slots"][0]["prompt"], asset["appearance"])
        self.assertEqual(img2img["i2i"]["image_ref"], {"path": "source.webp"})
        self.assertEqual(img2img["i2i"]["strength"], 0.75)
        self.assertEqual(img2img["generation"]["cfg_scale"], 6.0)
        self.assertEqual(img2img["generation"]["seed"], 44)

        inpaint = variation_plan_to_legacy_payload_material(asset, {
            "mode": "inpaint",
            "source_image": "source.webp",
            "mask": {"path": "mask.png"},
            "temporary_settings": {"strength": 1.0},
        })
        self.assertEqual(inpaint["action"], "infill")
        self.assertEqual(inpaint["i2i"]["mask_ref"], {"path": "mask.png"})

    def test_character_reference_plan_adds_temporary_ref_without_losing_saved_refs(self):
        cfg = self.config()
        asset = character_asset_from_legacy_record(
            cfg["characters"][0],
            char_refs=cfg["char_refs"],
            vibes=cfg["vibes"],
        )
        material = variation_plan_to_legacy_payload_material(asset, {
            "mode": "character-reference",
            "source_image": "source.webp",
            "reference": {"path": "new-reference.png"},
            "temporary_settings": {
                "reference_strength": -0.5,
                "reference_fidelity": 2.0,
                "steps": 8,
            },
        })
        self.assertEqual(material["action"], "generate")
        self.assertEqual(len(material["char_refs"]), 3)
        self.assertEqual(material["char_refs"][0]["strength"], -0.5)
        self.assertEqual(material["char_refs"][0]["fidelity"], 2.0)
        self.assertEqual(
            material["char_refs"][0]["image_ref"],
            {"path": "new-reference.png"},
        )
        self.assertEqual(material["generation"]["steps"], 8)
        self.assertEqual(len(material["vibes"]), 1)

    def test_only_explicitly_approved_proposal_becomes_append_candidates(self):
        legacy = self.config()["characters"][0]
        asset = character_asset_from_legacy_record(legacy)
        plan = plan_character_variation(asset, {
            "mode": "img2img",
            "source_image": "source.webp",
            "prompt_overrides": {
                "appearance": "1girl, pink hair",
                "outfit": "",
            },
        })
        proposal = accept_variation(
            asset,
            plan,
            {"image_ref": {"path": "pink.webp"}, "metadata": {"seed": 9}},
        )
        before = copy.deepcopy(legacy)
        with self.assertRaises(PermissionError):
            approved_proposal_to_legacy_candidates(
                legacy, proposal, approved=False
            )
        candidates = approved_proposal_to_legacy_candidates(
            legacy, proposal, approved=True
        )
        self.assertEqual(legacy, before)
        self.assertEqual(candidates["apply"], "append-only")
        self.assertEqual(
            candidates["variant_candidate"]["female"],
            "1girl, pink hair",
        )
        self.assertEqual(candidates["variant_candidate"]["clothed"], "")
        self.assertEqual(
            candidates["evidence_candidate"]["image_ref"],
            {"path": "pink.webp"},
        )
        self.assertEqual(
            candidates["variant_candidate"]["reference_ids"],
            ["ref-a", "missing-ref"],
        )
        self.assertEqual(
            candidates["variant_candidate"]["vibe_ids"], ["vibe-a"])
        self.assertEqual(candidates["original_record"], legacy)

    def test_only_explicit_selected_variation_overrides_whole_character_bundle(self):
        record = {
            "prompt": "base appearance",
            "outfit": "base outfit",
            "negative": "base negative",
            "selected_variant_id": "winter",
            "variants": [{
                "id": "winter",
                "name": "겨울",
                "female": "winter appearance",
                "clothed": "",
                "negative": "winter negative",
                "future": {"stay": True},
            }],
        }
        before = copy.deepcopy(record)
        selected = selected_variation_values(record)
        self.assertEqual(record, before)
        self.assertEqual(selected["prompt"], "winter appearance")
        self.assertEqual(selected["outfit"], "")
        self.assertEqual(selected["negative"], "winter negative")
        self.assertEqual(selected["selected_variant_id"], "winter")
        self.assertEqual(selected["selected_variant"]["future"], {"stay": True})
        missing = selected_variation_values(
            dict(record, selected_variant_id="removed"))
        self.assertEqual(missing["prompt"], "base appearance")
        self.assertEqual(missing["outfit"], "base outfit")
        self.assertEqual(missing["selected_variant_id"], "")

    def test_wrong_ranges_refs_and_foreign_proposals_are_rejected(self):
        asset = character_asset_from_legacy_record(
            self.config()["characters"][0]
        )
        with self.assertRaises(ValueError):
            variation_plan_to_legacy_payload_material(asset, {
                "mode": "img2img",
                "source_image": "source.webp",
                "temporary_settings": {"strength": 1.0},
            })
        with self.assertRaises(ValueError):
            variation_plan_to_legacy_payload_material(asset, {
                "mode": "inpaint",
                "source_image": "source.webp",
                "mask": "mask.png",
                "temporary_settings": {"noise": -0.1},
            })
        with self.assertRaises(ValueError):
            variation_plan_to_legacy_payload_material(asset, {
                "mode": "character-reference",
                "source_image": "source.webp",
                "reference": "reference.png",
                "temporary_settings": {"reference_fidelity": 2.1},
            })
        foreign = {
            "action": "proposal-only",
            "asset_id": "someone-else",
            "variant": {"status": "proposed"},
            "evidence": {"status": "proposed"},
        }
        with self.assertRaises(ValueError):
            approved_proposal_to_legacy_candidates(
                self.config()["characters"][0],
                foreign,
                approved=True,
            )


if __name__ == "__main__":
    unittest.main()
