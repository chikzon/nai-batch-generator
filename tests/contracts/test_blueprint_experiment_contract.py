# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import unittest

from src.nai_studio.domain.blueprint import (
    BLUEPRINT_SCHEMA,
    blueprint_fields,
    canonical_blueprint,
    canonical_generation_plan,
    fingerprint_blueprint,
    resolve_blueprint_layers,
    summarize_blueprint,
)
from src.nai_studio.domain.experiment import (
    canonical_experiment_rule,
    expand_experiment,
    regeneration_identity,
)
from src.nai_studio.domain.project_inheritance import (
    blueprint_common,
    local_overrides,
    resolve_inheritance,
)


class BlueprintExperimentContractTests(unittest.TestCase):
    def test_existing_blueprint_api_stays_compatible_and_lossless(self):
        raw = {
            "style": {"name": "A", "base": "long::prompt"},
            "characters": [{"id": "c1", "prompt": "original"}],
            "future": {"nested": ["kept"]},
        }
        before = copy.deepcopy(raw)
        canonical = canonical_blueprint(raw)
        self.assertEqual(raw, before)
        self.assertEqual(canonical["schema"], BLUEPRINT_SCHEMA)
        self.assertEqual(canonical["future"], {"nested": ["kept"]})
        self.assertIn("generation", blueprint_fields())
        self.assertEqual(summarize_blueprint(canonical)["style_name"], "A")
        self.assertEqual(
            fingerprint_blueprint(raw),
            fingerprint_blueprint(copy.deepcopy(raw)),
        )

    def test_rich_plan_preserves_character_style_cast_scene_and_execution_values(self):
        raw = {
            "source": {"kind": "evidence", "url": "https://example.invalid/1"},
            "style": {
                "id": "s1",
                "base": "base",
                "negative": "negative",
                "params": {"cfg_scale": 5.2},
                "evidence": [{"image": "proof.webp"}],
            },
            "characters": [{
                "id": "c1",
                "appearance": "red hair",
                "clothed": "white dress",
                "negative": "bad hands",
                "variant": {"group": "dress", "id": "v1"},
                "reference_ids": ["ref:1"],
                "vibe_ids": ["vibe:1"],
                "include": ["smile"],
                "exclude": ["hat"],
                "position": {"x": 0.3, "y": 0.5},
                "relations": [{"with": "c2", "kind": "looking at"}],
            }],
            "resources": {
                "vibes": [{"id": "vibe:1", "strength": 0.7}],
                "character_references": [{"id": "ref:1", "strength": 1.2}],
            },
            "setting": {
                "scene_values": {"common": "park"},
                "character_values": {"c1": {"include": ["standing"]}},
                "relations": [{"from": "c1", "to": "c2"}],
                "steps": [{"id": "step:1", "include": ["day"]}],
                "families": ["daylight"],
                "options": {"weather": ["sunny", "rain"]},
                "cast": [{"id": "c1", "appearance": "red hair"}],
                "repeat": 3,
                "order": ["step:1"],
                "reservation": {"at": "2026-08-01T00:00:00Z"},
            },
            "generation": {
                "width": 832,
                "height": 1216,
                "seed": 42,
                "settings": {"sampler": "k_euler"},
                "final": {
                    "prompt": "resolved",
                    "payload": {"input": "resolved"},
                    "cost": {"anlas": 0},
                },
            },
        }
        plan = canonical_generation_plan(raw)
        self.assertEqual(plan["style"]["generation_settings"]["cfg_scale"], 5.2)
        self.assertEqual(plan["characters"][0]["variant"]["id"], "v1")
        self.assertEqual(plan["characters"][0]["reference_ids"], ["ref:1"])
        self.assertEqual(plan["setting"]["character_values"]["c1"]["include"], ["standing"])
        self.assertEqual(plan["setting"]["reservation"]["at"], "2026-08-01T00:00:00Z")
        self.assertEqual(plan["generation"]["resolution"], {"width": 832, "height": 1216})
        self.assertEqual(plan["generation"]["final"]["payload"]["input"], "resolved")
        explicit_empty = canonical_generation_plan({
            "characters": [{
                "reference_ids": [],
                "references": ["must-not-reappear"],
            }],
        })
        self.assertEqual(explicit_empty["characters"][0]["reference_ids"], [])

    def test_priority_resolution_reports_provenance_and_every_real_conflict(self):
        resolved = resolve_blueprint_layers(
            [
                {
                    "source": {"id": "project"},
                    "priority": 10,
                    "blueprint": {
                        "style": {
                            "base": "artist",
                            "negative": "project negative",
                        },
                        "generation": {"seed": 1, "width": 832},
                    },
                },
                {
                    "source": {"id": "setting"},
                    "priority": 20,
                    "blueprint": {
                        "generation": {"seed": 55},
                        "setting": {"scene_values": {"place": "park"}},
                    },
                },
                {
                    "source": {"id": "current"},
                    "priority": 30,
                    "blueprint": {
                        "style": {"negative": ""},
                        "generation": {"seed": 99},
                    },
                },
            ],
            base={"generation": {"seed": 7, "height": 1216}},
        )
        self.assertEqual(resolved["blueprint"]["generation"]["seed"], 99)
        self.assertEqual(resolved["blueprint"]["generation"]["height"], 1216)
        self.assertEqual(resolved["blueprint"]["style"]["base"], "artist")
        self.assertEqual(resolved["blueprint"]["style"]["negative"], "")
        self.assertEqual(
            resolved["blueprint"]["setting"]["scene_values"]["place"], "park")
        self.assertEqual(
            resolved["provenance"]["/generation/seed"]["source"]["id"],
            "current",
        )
        conflict = next(
            item for item in resolved["conflicts"]
            if item["path"] == "/generation/seed"
        )
        self.assertEqual(conflict["rule"], "higher-priority")
        self.assertEqual(conflict["winner"]["value"], 99)

        parent = blueprint_common({
            "style": {"base": "parent", "negative": "keep"},
            "generation": {"seed": 1, "width": 832},
        })
        current = canonical_generation_plan(copy.deepcopy(parent))
        current["style"]["base"] = "local"
        overrides = local_overrides(current, parent)
        inherited = resolve_inheritance(
            current,
            [{
                "id": "p", "name": "P", "blueprint": parent,
                "fingerprint": fingerprint_blueprint(parent),
            }],
            {
                "project_id": "p",
                "accepted_blueprint": parent,
                "accepted_fingerprint": fingerprint_blueprint(parent),
                "local_overrides": overrides,
            },
        )
        self.assertEqual(inherited["blueprint"]["style"]["base"], "local")
        self.assertEqual(inherited["blueprint"]["style"]["negative"], "keep")
        self.assertEqual(
            inherited["provenance"]["/style/base"]["source"]["kind"],
            "current-overrides",
        )
        self.assertEqual(
            inherited["provenance"]["/style/negative"]["source"]["kind"],
            "project",
        )

    def test_style_character_seed_cross_is_deterministic_and_resumable(self):
        blueprint = {
            "style": {"id": "current", "base": "base"},
            "characters": [],
            "generation": {"width": 512, "height": 512},
        }
        rule = {
            "mode": "cross",
            "styles": [
                {"id": "s1", "base": "one"},
                {"id": "s2", "base": "two"},
            ],
            "characters": [
                {"id": "c1", "appearance": "red"},
                {"id": "c2", "appearance": "blue"},
            ],
            "seeds": [11, 12],
            "fixed": {"generation.steps": 8},
        }
        first = expand_experiment(blueprint, rule)
        second = expand_experiment(copy.deepcopy(blueprint), copy.deepcopy(rule))
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["total"], 8)
        self.assertEqual(
            [item["id"] for item in first["cells"]],
            [item["id"] for item in second["cells"]],
        )
        self.assertEqual(len({item["id"] for item in first["cells"]}), 8)
        self.assertEqual(first["cells"][0]["blueprint"]["generation"]["steps"], 8)
        self.assertEqual(first["cells"][0]["blueprint"]["generation"]["seed"], 11)
        resumed = expand_experiment(
            blueprint,
            rule,
            completed_ids=[first["cells"][0]["id"]],
        )
        self.assertEqual(resumed["completed"], 1)
        self.assertEqual(resumed["pending"], 7)
        self.assertEqual(resumed["cells"][0]["status"], "completed")
        retry1 = regeneration_identity(first["cells"][0], 1)
        retry2 = regeneration_identity(first["cells"][0], 2)
        self.assertEqual(retry1["cell_id"], retry2["cell_id"])
        self.assertNotEqual(retry1["request_id"], retry2["request_id"])

    def test_character_setting_selected_groups_and_parameter_axes(self):
        rule = canonical_experiment_rule({
            "mode": "character×setting",
            "characters": [{"id": "c1"}, {"id": "c2"}],
            "settings": [{"id": "p1"}, {"id": "p2"}],
            "axes": [{
                "name": "generation.cfg_scale",
                "values": [4.0, 5.0],
            }],
        })
        self.assertEqual(
            [axis["name"] for axis in rule["axes"]],
            ["generation.cfg_scale", "character", "setting"],
        )
        plan = expand_experiment({}, rule)
        self.assertEqual(plan["total"], 8)
        self.assertEqual(
            plan["cells"][-1]["blueprint"]["generation"]["cfg_scale"],
            5.0,
        )
        selected = canonical_experiment_rule({
            "mode": "selected_groups",
            "selected_groups": {
                "generation.sampler": ["k_euler", "k_dpmpp_2m"],
                "generation.scheduler": ["native", "karras"],
            },
        })
        self.assertEqual(
            [axis["name"] for axis in selected["axes"]],
            ["generation.sampler", "generation.scheduler"],
        )
        self.assertEqual(expand_experiment({}, selected)["total"], 4)


if __name__ == "__main__":
    unittest.main()
