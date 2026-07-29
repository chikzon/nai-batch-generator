# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
import unittest

from src.nai_studio.services.experiment_bridge import (
    expand_legacy_experiment_cells,
)
from src.nai_studio.services.experiment_execution_bridge import (
    legacy_execution_material,
    legacy_execution_queue,
    regenerate_legacy_execution_material,
)


class ExperimentExecutionBridgeContractTests(unittest.TestCase):
    def cfg(self):
        return {
            "token": "must-never-leave-runtime",
            "base_prompt": "base\n1.2::weighted text::",
            "negative_prompt": "negative\n||red||",
            "style_name": "current",
            "nai_seed": 101,
            "width": 832,
            "height": 1216,
            "cfg_scale": 5.0,
            "char_slots": [{
                "id": "current",
                "name": "Current",
                "prompt": "1girl\n{a|b}",
                "outfit": "white dress",
                "negative": "bad hands",
                "enabled": True,
            }],
            "char_centers": [{"x": 0.25, "y": 0.75}],
            "setting_state": {
                "park": {
                    "use": True,
                    "selected": ["bench"],
                    "opts": {"weather": "sunny"},
                    "cast": [],
                },
            },
        }

    def sources(self):
        styles = [{
            "_compare_id": "style-one",
            "_compare_name": "Style One",
            "base": "style\n1.1::line::",
            "negative": "style negative",
            "params": {
                "scale": 6.5,
                "noise_schedule": "karras",
                "width": 640,
                "height": 960,
            },
        }]
        characters = [{
            "_compare_id": "char-one",
            "_compare_name": "Character One",
            "female": "1girl\nvery long appearance",
            "clothed": "artistically transformed outfit",
            "negative": "character negative",
            "position": {"x": 0.4, "y": 0.6},
            "reference_ids": ["ref-one"],
            "vibe_ids": ["vibe-one"],
        }]
        settings = [{
            "id": "setting-one",
            "name": "Setting One",
            "state": {
                "use": True,
                "selected": ["scene-a"],
                "opts": {"weather": "rain"},
                "cast": [],
            },
        }]
        return styles, characters, settings

    def plan(self, mode="both", **options):
        data = {
            "mode": mode,
            "same_seed": True,
            "seed": 100,
            "seed_count": 1,
            "fixed_size": False,
            "limit": 0,
            "include_refs": False,
        }
        data.update(options)
        return {"options": data}

    def expanded(self, mode="both", **options):
        styles, characters, settings = self.sources()
        return expand_legacy_experiment_cells(
            self.cfg(),
            self.plan(mode, **options),
            styles=styles,
            characters=characters,
            settings=settings,
        )

    def test_existing_modes_keep_the_exact_legacy_job_key_and_material_shape(self):
        for mode in ("styles", "characters", "both"):
            expanded = self.expanded(mode)
            cell = expanded["cells"][0]
            material = legacy_execution_material(cell, self.cfg())
            self.assertEqual(material["job"]["key"], cell["legacy_job_key"])
            self.assertEqual(
                material["resume_key"], cell["legacy_resume_key"]
            )
            self.assertEqual(
                material["job"]["seed_index"],
                cell["seed_material"]["seed_index"],
            )
            self.assertEqual(material["seed"], 100)

    def test_style_character_setting_and_selected_parameters_become_executor_input(self):
        styles, characters, settings = self.sources()
        expanded = expand_legacy_experiment_cells(
            self.cfg(),
            self.plan("selected"),
            styles=styles,
            characters=characters,
            settings=settings,
            selected={
                "styles": ["style-one"],
                "characters": ["char-one"],
                "settings": ["setting-one"],
                "axes": {
                    "generation.cfg_scale": [7.25],
                    "generation.sampler": ["k_dpmpp_2m"],
                    "payload.parameters.extra_noise_seed": [44],
                    "payload.parameters.api_token": ["must-not-survive"],
                },
            },
        )
        material = legacy_execution_material(expanded["cells"][0], self.cfg())
        self.assertEqual(
            material["config_overrides"]["base_prompt"],
            "style\n1.1::line::",
        )
        self.assertEqual(
            material["config_overrides"]["negative_prompt"],
            "style negative",
        )
        self.assertEqual(material["config_overrides"]["cfg_scale"], 7.25)
        self.assertEqual(
            material["config_overrides"]["sampler"], "k_dpmpp_2m"
        )
        self.assertEqual(
            material["payload_overrides"]["parameters"]["extra_noise_seed"],
            44,
        )
        self.assertNotIn(
            "api_token", material["payload_overrides"]["parameters"]
        )
        self.assertEqual(
            material["char_slots"][0]["prompt"],
            "1girl\nvery long appearance",
        )
        self.assertEqual(
            material["char_slots"][0]["outfit"],
            "artistically transformed outfit",
        )
        self.assertEqual(
            material["char_slots"][0]["negative"], "character negative"
        )
        self.assertEqual(material["char_centers"][0], {"x": 0.4, "y": 0.6})
        self.assertEqual(
            material["char_slots"][0]["reference_ids"], ["ref-one"])
        self.assertEqual(
            material["char_slots"][0]["vibe_ids"], ["vibe-one"])
        self.assertEqual(
            material["setting_state"]["setting-one"]["selected"], ["scene-a"]
        )

    def test_character_setting_cross_is_materialized_without_merging_prompts(self):
        expanded = self.expanded("character_setting")
        material = legacy_execution_material(expanded["cells"][0], self.cfg())
        self.assertEqual(len(material["char_slots"]), 1)
        self.assertEqual(
            material["char_slots"][0]["prompt"],
            "1girl\nvery long appearance",
        )
        self.assertEqual(
            material["char_slots"][0]["outfit"],
            "artistically transformed outfit",
        )
        self.assertNotIn(
            "artistically transformed outfit",
            material["char_slots"][0]["prompt"],
        )
        self.assertEqual(list(material["setting_state"]), ["setting-one"])

    def test_runtime_seed_resume_and_single_cell_regeneration_are_stable(self):
        expanded = self.expanded(
            "both", same_seed=True, seed=0, seed_count=2
        )
        first = legacy_execution_material(
            expanded["cells"][0], self.cfg(), runtime_base_seed=900
        )
        second = legacy_execution_material(
            expanded["cells"][1], self.cfg(), runtime_base_seed=900
        )
        self.assertEqual(first["seed"], 900)
        self.assertEqual(second["seed"], 100903)

        completed = expanded["cells"][0]["legacy_resume_key"]
        queue = legacy_execution_queue(
            expanded, self.cfg(), completed_keys=[completed],
            runtime_base_seed=900,
        )
        self.assertEqual(len(queue["items"]), 1)
        self.assertEqual(queue["skipped_completed"], 1)

        rerun1 = regenerate_legacy_execution_material(
            expanded["cells"][0], self.cfg(), attempt=1,
            runtime_base_seed=900,
        )
        rerun2 = regenerate_legacy_execution_material(
            expanded["cells"][0], self.cfg(), attempt=2,
            runtime_base_seed=900,
        )
        self.assertEqual(rerun1["resume_key"], rerun2["resume_key"])
        self.assertEqual(rerun1["seed"], rerun2["seed"])
        self.assertNotEqual(rerun1["request_id"], rerun2["request_id"])

    def test_inputs_are_immutable_prompts_are_untrimmed_and_secrets_are_absent(self):
        expanded = self.expanded("both")
        cfg = self.cfg()
        cell = expanded["cells"][0]
        before = copy.deepcopy((cfg, cell))
        material = legacy_execution_material(cell, cfg)
        self.assertEqual((cfg, cell), before)
        text = json.dumps(material, ensure_ascii=False)
        self.assertNotIn("must-never-leave-runtime", text)
        self.assertNotIn('"token"', text)
        self.assertIn("style\\n1.1::line::", text)
        self.assertIn("1girl\\nvery long appearance", text)


if __name__ == "__main__":
    unittest.main()
