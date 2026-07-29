# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
import unittest

from src.nai_studio import legacy_app as APP
from src.nai_studio.services.blueprint_execution_bridge import (
    MATERIAL_SCHEMA,
    single_generation_legacy_material,
)


class BlueprintExecutionBridgeContractTests(unittest.TestCase):
    def fixture(self):
        cfg = copy.deepcopy(APP.DEFAULT_CONFIG)
        cfg.update({
            "token": "pst-runtime-only-secret",
            "style_name": "원문 그림체",
            "base_prompt": "base\n1.2::weighted::",
            "negative_prompt": "negative\n||red||",
            "model": "nai-diffusion-4-5-full",
            "width": 896,
            "height": 1152,
            "nai_seed": 429496,
            "steps": 31,
            "cfg_scale": 6.25,
            "cfg_rescale": 0.42,
            "sampler": "k_dpmpp_2m",
            "scheduler": "native",
            "uc_preset": 4,
            "quality_toggle": True,
            "variety": True,
            "smea": False,
            "smea_dyn": False,
            "dynamic_thresholding": False,
            "uncond_scale": 0.0,
            "controlnet_strength": 1.0,
            "prefer_brownian": False,
            "deliberate_euler_ancestral_bug": True,
            "use_coords": True,
            "save_format": "png",
            "save_quality": 91,
            "save_clean": False,
            "save_max_side": 1536,
            "out_dir": "D:/results",
            "out_by_date": True,
            "char_slots": [{
                "id": "a",
                "name": "A",
                "prompt": "red hair\n# local note",
                "outfit": "white dress",
                "negative": "bad hands",
                "enabled": True,
                "variant": {"group": "A", "name": "white"},
                "reference_ids": ["ref-a"],
                "vibe_ids": ["vibe-a"],
                "future_character_field": {"keep": 17},
            }, {
                "id": "off",
                "name": "OFF",
                "prompt": "must not execute",
                "outfit": "",
                "negative": "",
                "enabled": False,
            }, {
                "id": "b",
                "name": "B",
                "prompt": "blue hair",
                "outfit": "black coat",
                "negative": "text",
                "enabled": True,
                "reference_ids": [],
                "vibe_ids": [],
            }],
            "char_centers": [
                {"x": 0.13, "y": 0.87},
                {"x": 0.5, "y": 0.5},
                {"x": 0.74, "y": 0.28},
            ],
            "vibes": [{
                "id": "vibe-a",
                "name": "V",
                "enabled": True,
                "strength": 0.77,
                "info": 0.61,
                "encoded": "opaque-encoding",
            }],
            "char_refs": [{
                "id": "ref-a",
                "name": "R",
                "enabled": True,
                "strength": 1.4,
                "fidelity": 0.3,
                "image": "opaque-image",
            }],
        })
        return cfg

    def test_generation_blueprint_matches_existing_single_assembly(self):
        cfg = self.fixture()
        blueprint = APP.generation_blueprint(cfg)
        material = single_generation_legacy_material(blueprint)
        people, centers = APP.active_people(
            cfg["char_slots"], cfg["char_centers"]
        )

        self.assertEqual(material["schema"], MATERIAL_SCHEMA)
        self.assertEqual(material["call"]["base_prompt"], cfg["base_prompt"])
        self.assertEqual(
            material["call"]["negative_prompt"], cfg["negative_prompt"]
        )
        self.assertEqual(material["call"]["characters"], people)
        self.assertEqual(material["call"]["char_centers"], centers)
        self.assertEqual(
            material["call"]["positions"],
            [
                {"enabled": True, **centers[0]},
                {"enabled": True, **centers[1]},
            ],
        )
        self.assertEqual(material["call"]["seed"], APP.fixed_seed(cfg))
        for key in APP.BLUEPRINT_GENERATION_KEYS:
            if key in ("nai_seed", "width", "height"):
                continue
            self.assertEqual(
                material["call"]["generation_settings"][key], cfg[key]
            )
        self.assertEqual(
            material["call"]["resources"]["vibes"], cfg["vibes"]
        )
        self.assertEqual(
            material["call"]["resources"]["character_references"],
            cfg["char_refs"],
        )
        self.assertEqual(
            material["config_overrides"]["save_format"], "png"
        )
        self.assertEqual(
            material["config_overrides"]["out_dir"], "D:/results"
        )

    def test_character_split_unknowns_and_resource_selection_are_lossless(self):
        blueprint = APP.generation_blueprint(self.fixture())
        blueprint["characters"][0]["future_character_field"] = {"keep": 17}
        material = single_generation_legacy_material(blueprint)
        first = material["config_overrides"]["char_slots"][0]
        self.assertEqual(first["prompt"], "red hair\n# local note")
        self.assertEqual(first["outfit"], "white dress")
        self.assertEqual(first["negative"], "bad hands")
        self.assertEqual(first["reference_ids"], ["ref-a"])
        self.assertEqual(first["vibe_ids"], ["vibe-a"])
        self.assertEqual(
            first["future_character_field"], {"keep": 17}
        )
        self.assertEqual(
            material["call"]["characters"][0]["prompt"],
            "red hair, white dress",
        )
        self.assertNotIn(
            "must not execute",
            json.dumps(material, ensure_ascii=False),
        )

    def test_blank_character_keeps_editing_slot_but_not_a_misaligned_call_center(self):
        cfg = self.fixture()
        cfg["char_slots"] = [{
            "id": "blank",
            "name": "Blank",
            "prompt": "",
            "outfit": "",
            "negative": "blank negative",
            "enabled": True,
        }, {
            "id": "real",
            "name": "Real",
            "prompt": "blue hair",
            "outfit": "black coat",
            "negative": "real negative",
            "enabled": True,
        }]
        cfg["char_centers"] = [
            {"x": 0.1, "y": 0.2},
            {"x": 0.8, "y": 0.9},
        ]
        material = single_generation_legacy_material(
            APP.generation_blueprint(cfg)
        )
        people, centers = APP.active_people(
            cfg["char_slots"], cfg["char_centers"]
        )

        self.assertEqual(material["call"]["characters"], people)
        self.assertEqual(material["call"]["char_centers"], centers)
        self.assertEqual(material["call"]["positions"], [
            {"enabled": True, "x": 0.8, "y": 0.9},
        ])
        self.assertEqual(
            [slot["id"] for slot in material["config_overrides"]["char_slots"]],
            ["blank", "real"],
        )
        self.assertEqual(
            material["config_overrides"]["char_centers"],
            cfg["char_centers"],
        )

    def test_input_is_immutable_unknown_fields_survive_and_credentials_do_not(self):
        blueprint = APP.generation_blueprint(self.fixture())
        blueprint["future_top_level"] = {
            "keep": ["verbatim"],
            "accessToken": "opaque-secret",
        }
        blueprint["generation"]["future_generation"] = {
            "mode": "keep-me",
            "token": "must-not-survive",
        }
        blueprint["source"]["note"] = (
            "safe prefix pst-ne-secret-in-string safe suffix"
        )
        before = copy.deepcopy(blueprint)
        material = single_generation_legacy_material(blueprint)
        self.assertEqual(blueprint, before)
        self.assertEqual(
            material["passthrough"]["blueprint"]["future_top_level"],
            {"keep": ["verbatim"]},
        )
        self.assertEqual(
            material["passthrough"]["generation"]["future_generation"],
            {"mode": "keep-me"},
        )
        text = json.dumps(material, ensure_ascii=False)
        for secret in (
            "pst-runtime-only-secret",
            "opaque-secret",
            "must-not-survive",
            "pst-ne-secret-in-string",
        ):
            self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
