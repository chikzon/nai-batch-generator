# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
import unittest

from src.nai_studio.services.experiment_bridge import (
    expand_legacy_experiment_cells,
    experiment_rule_from_legacy,
    legacy_blueprint_from_config,
    regeneration_identity_for_legacy_cell,
)


class ExperimentBridgeContractTests(unittest.TestCase):
    def cfg(self):
        return {
            "token": "must-not-cross",
            "base_prompt": "base",
            "negative_prompt": "negative",
            "style_name": "current",
            "nai_seed": 77,
            "width": 832,
            "height": 1216,
            "steps": 8,
            "char_slots": [{
                "id": "current-char",
                "prompt": "1girl, current",
                "outfit": "white dress",
                "negative": "bad hands",
            }],
            "char_centers": [{"x": 0.3, "y": 0.5}],
            "char_refs": [{"id": "ref1", "token": "nested-secret"}],
            "vibes": [{"id": "vibe1"}],
            "setting_state": {
                "park": {
                    "use": True,
                    "selected": ["scene1"],
                    "stages": [1, 2],
                    "opts": {"weather": "sunny"},
                    "cast": [{"prompt": "1girl, cast"}],
                },
                "disabled": {"use": False, "selected": ["scene2"]},
            },
        }

    def sources(self):
        styles = [
            {"_compare_id": "s1", "_compare_name": "Style 1", "base": "one"},
            {"_compare_id": "s2", "_compare_name": "Style 2", "base": "two"},
        ]
        characters = [
            {"_compare_id": "c1", "_compare_name": "Char 1", "female": "red"},
            {"_compare_id": "c2", "_compare_name": "Char 2", "female": "blue"},
        ]
        return styles, characters

    def plan(self, mode="both", **options):
        data = {
            "mode": mode,
            "same_seed": True,
            "seed": 100,
            "seed_count": 1,
            "fixed_size": True,
            "width": 512,
            "height": 768,
            "limit": 0,
            "include_refs": False,
        }
        data.update(options)
        return {"options": data}

    def test_legacy_config_projection_is_immutable_and_excludes_all_tokens(self):
        cfg = self.cfg()
        before = copy.deepcopy(cfg)
        blueprint = legacy_blueprint_from_config(cfg)
        self.assertEqual(cfg, before)
        serialized = json.dumps(blueprint, ensure_ascii=False)
        self.assertNotIn("must-not-cross", serialized)
        self.assertNotIn("nested-secret", serialized)
        self.assertNotIn('"token"', serialized)
        self.assertEqual(blueprint["style"]["base"], "base")
        self.assertEqual(blueprint["characters"][0]["appearance"], "1girl, current")
        self.assertEqual(blueprint["characters"][0]["position"]["x"], 0.3)

    def test_existing_styles_characters_and_both_modes_expand_exact_counts(self):
        styles, characters = self.sources()
        styles_only = expand_legacy_experiment_cells(
            self.cfg(), self.plan("styles", seed_count=2),
            styles=styles, characters=characters,
        )
        chars_only = expand_legacy_experiment_cells(
            self.cfg(), self.plan("characters", seed_count=2),
            styles=styles, characters=characters,
        )
        both = expand_legacy_experiment_cells(
            self.cfg(), self.plan("both", seed_count=2),
            styles=styles, characters=characters,
        )
        self.assertEqual(styles_only["total"], 4)
        self.assertEqual(chars_only["total"], 4)
        self.assertEqual(both["total"], 8)
        self.assertEqual(
            both["cells"][0]["blueprint"]["generation"]["width"], 512
        )
        self.assertEqual(
            both["cells"][0]["legacy_material"]["style"]["_compare_id"], "s1"
        )
        self.assertEqual(
            both["cells"][0]["legacy_material"]["character"]["_compare_id"], "c1"
        )
        self.assertTrue(
            both["cells"][0]["legacy_job_key"].startswith("job-")
        )
        self.assertEqual(
            both["cells"][0]["legacy_job_key"],
            "job-eb74a3a134b9e107415d",
        )

    def test_character_setting_and_manual_selected_axes_expand(self):
        _, characters = self.sources()
        char_setting = expand_legacy_experiment_cells(
            self.cfg(),
            self.plan("character_setting"),
            characters=characters,
        )
        self.assertEqual(char_setting["total"], 2)
        self.assertEqual(
            char_setting["cells"][0]["legacy_material"]["setting"]["id"],
            "park",
        )

        styles, characters = self.sources()
        selected = expand_legacy_experiment_cells(
            self.cfg(),
            self.plan("selected"),
            styles=styles,
            characters=characters,
            selected={
                "styles": ["s2"],
                "characters": ["c1"],
                "axes": {
                    "generation.cfg_scale": [4.0, 5.0],
                    "generation.sampler": ["k_euler", "k_dpmpp_2m"],
                },
            },
        )
        self.assertEqual(selected["total"], 4)
        for cell in selected["cells"]:
            self.assertEqual(
                cell["legacy_material"]["style"]["_compare_id"], "s2"
            )
            self.assertEqual(
                cell["legacy_material"]["character"]["_compare_id"], "c1"
            )
        self.assertEqual(
            {
                cell["legacy_material"]["selected_axes"]["generation.cfg_scale"]
                for cell in selected["cells"]
            },
            {4.0, 5.0},
        )

    def test_same_seed_multi_seed_and_per_cell_seed_policy_are_preserved(self):
        styles, characters = self.sources()
        same = expand_legacy_experiment_cells(
            self.cfg(),
            self.plan("both", same_seed=True, seed=100, seed_count=2),
            styles=styles, characters=characters,
        )
        index_zero = [
            cell["seed_material"]["resolved_seed"]
            for cell in same["cells"]
            if cell["seed_material"]["seed_index"] == 0
        ]
        index_one = [
            cell["seed_material"]["resolved_seed"]
            for cell in same["cells"]
            if cell["seed_material"]["seed_index"] == 1
        ]
        self.assertEqual(set(index_zero), {100})
        self.assertEqual(set(index_one), {100103})
        self.assertEqual(
            [
                cell["seed_material"]["seed_index"]
                for cell in same["cells"][:4]
            ],
            [0, 1, 0, 1],
        )

        different = expand_legacy_experiment_cells(
            self.cfg(),
            self.plan("both", same_seed=False, seed=100, seed_count=1),
            styles=styles, characters=characters,
        )
        self.assertEqual(
            {
                cell["seed_material"]["resolved_seed"]
                for cell in different["cells"]
            },
            {100, 100103, 200106, 300109},
        )

    def test_resume_key_and_single_cell_regeneration_identity_are_stable(self):
        styles, characters = self.sources()
        first = expand_legacy_experiment_cells(
            self.cfg(), self.plan("both"),
            styles=styles, characters=characters,
        )
        second = expand_legacy_experiment_cells(
            copy.deepcopy(self.cfg()), copy.deepcopy(self.plan("both")),
            styles=copy.deepcopy(styles), characters=copy.deepcopy(characters),
        )
        self.assertEqual(
            [cell["legacy_resume_key"] for cell in first["cells"]],
            [cell["legacy_resume_key"] for cell in second["cells"]],
        )
        completed_key = first["cells"][1]["legacy_resume_key"]
        resumed = expand_legacy_experiment_cells(
            self.cfg(), self.plan("both"),
            styles=styles, characters=characters,
            completed_keys=[completed_key],
        )
        self.assertEqual(resumed["completed"], 1)
        retry1 = regeneration_identity_for_legacy_cell(first["cells"][0], 1)
        retry2 = regeneration_identity_for_legacy_cell(first["cells"][0], 2)
        self.assertEqual(retry1["cell_id"], retry2["cell_id"])
        self.assertEqual(
            retry1["legacy_resume_key"],
            first["cells"][0]["legacy_resume_key"],
        )
        self.assertNotEqual(retry1["request_id"], retry2["request_id"])

    def test_rule_projection_does_not_mutate_plan_sources_or_selection(self):
        cfg, plan = self.cfg(), self.plan("selected")
        styles, characters = self.sources()
        selected = {"styles": ["s1"], "axes": {"generation.steps": [6, 8]}}
        before = copy.deepcopy((cfg, plan, styles, characters, selected))
        rule = experiment_rule_from_legacy(
            cfg, plan, styles=styles, characters=characters, selected=selected
        )
        self.assertEqual((cfg, plan, styles, characters, selected), before)
        self.assertEqual(rule["mode"], "selected_groups")


if __name__ == "__main__":
    unittest.main()
