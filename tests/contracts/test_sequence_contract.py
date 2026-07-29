# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import unittest

from src.nai_studio.domain.sequence import (
    SEQUENCE_SCHEMA,
    canonical_sequence_plan,
    fingerprint_sequence_plan,
    next_sequence_step,
    resolve_sequence_step,
    sequence_plan_id,
)


LONG_PROMPT = (
    "1.2::masterpiece::, {sunrise|night}, <hero>, 한글, 😀, C:\\asset\n"
) * 120


class SequenceContractTests(unittest.TestCase):
    def base(self):
        return {
            "schema": "nai-generation-blueprint/v1",
            "style": {
                "id": "style:base",
                "base": LONG_PROMPT,
                "negative": "lowres",
                "generation_settings": {"cfg_scale": 5.5},
            },
            "characters": [
                {
                    "id": "character:a",
                    "appearance": "1girl, red hair",
                    "clothed": "white dress",
                    "negative": "bad hands",
                },
                {
                    "id": "character:b",
                    "appearance": "1boy, blue hair",
                    "clothed": "black jacket",
                    "negative": "bad anatomy",
                },
            ],
            "resources": {"vibes": [{"id": "vibe:base"}]},
            "setting": {
                "scene_values": {
                    "background": "old room",
                    "include": "soft light",
                },
            },
            "generation": {
                "resolution": {"width": 832, "height": 1216},
                "schedule": {},
            },
            "future_blueprint_field": {"preserve": True},
        }

    def plan(self, progression="once"):
        return {
            "name": "연속 장면",
            "progression": progression,
            "freeze": {
                "style": True,
                "characters": True,
                "wildcards": True,
            },
            "repeat": 2,
            "steps": [
                {
                    "id": "intro",
                    "name": "도입",
                    "include": LONG_PROMPT,
                    "exclude": "daylight",
                    "rating": "general",
                    "resolution": {"width": 1024, "height": 1024},
                    "seed_policy": {"mode": "fixed", "seed": 42},
                    "character_overrides": {
                        "character:a": {"negative": "extra fingers"},
                    },
                    "style_overrides": {
                        "generation_settings": {"cfg_scale": 6.0},
                    },
                    "background": "train station",
                    "outfit": {"character:a": "red coat"},
                    "vibe_continuity": {"source": "none"},
                    "repeat": 1,
                },
                {
                    "id": "walk",
                    "name": "이동",
                    "carry": {"background": True, "outfit": True},
                    "vibe_continuity": {
                        "source": "previous",
                        "strength": 0.65,
                    },
                    "future_step_field": {"preserve": "yes"},
                },
            ],
            "order": ["intro", "walk"],
            "future_plan_field": {"preserve": [1, 2, 3]},
        }

    def test_canonical_plan_preserves_prompts_freeze_repeat_order_and_future_fields(self):
        source = self.plan()
        before = copy.deepcopy(source)
        plan = canonical_sequence_plan(source)

        self.assertEqual(source, before)
        self.assertEqual(plan["schema"], SEQUENCE_SCHEMA)
        self.assertEqual(plan["steps"][0]["include"], LONG_PROMPT)
        self.assertEqual(plan["freeze"], {
            "style": True,
            "characters": True,
            "wildcards": True,
        })
        self.assertEqual(plan["repeat"], 2)
        self.assertEqual(plan["order"], ["intro", "walk"])
        self.assertEqual(
            plan["steps"][1]["future_step_field"],
            {"preserve": "yes"},
        )
        self.assertEqual(
            plan["future_plan_field"],
            {"preserve": [1, 2, 3]},
        )

    def test_step_and_plan_identity_are_stable_across_key_order_and_timestamps(self):
        first = self.plan()
        first["updated_at"] = "2026-07-29T00:00:00Z"
        second = copy.deepcopy(first)
        second["updated_at"] = "2030-01-01T00:00:00Z"
        second = dict(reversed(list(second.items())))

        self.assertEqual(sequence_plan_id(first), sequence_plan_id(second))
        self.assertEqual(
            fingerprint_sequence_plan(first),
            fingerprint_sequence_plan(second),
        )
        first_steps = canonical_sequence_plan(first)["steps"]
        second_steps = canonical_sequence_plan(second)["steps"]
        self.assertEqual(
            [item["fingerprint"] for item in first_steps],
            [item["fingerprint"] for item in second_steps],
        )

    def test_cycle_wraps_while_once_and_manual_stop_at_boundaries(self):
        cycle = self.plan("cycle")
        self.assertEqual(next_sequence_step(cycle)["id"], "intro")
        self.assertEqual(
            next_sequence_step(cycle, "intro", "forward")["id"],
            "walk",
        )
        self.assertEqual(
            next_sequence_step(cycle, "walk", "forward")["id"],
            "intro",
        )
        self.assertEqual(
            next_sequence_step(cycle, "intro", "backward")["id"],
            "walk",
        )

        for progression in ("once", "manual"):
            with self.subTest(progression=progression):
                plan = self.plan(progression)
                self.assertIsNone(next_sequence_step(plan, "walk", "forward"))
                self.assertIsNone(
                    next_sequence_step(plan, "intro", "backward"),
                )
                self.assertEqual(
                    next_sequence_step(plan, "intro", "forward")["id"],
                    "walk",
                )

    def test_resolve_applies_only_explicit_overrides_and_preserves_input(self):
        base = self.base()
        plan = self.plan()
        base_before = copy.deepcopy(base)
        plan_before = copy.deepcopy(plan)
        resolved = resolve_sequence_step(base, plan, "intro")

        self.assertEqual(base, base_before)
        self.assertEqual(plan, plan_before)
        self.assertEqual(resolved["style"]["base"], LONG_PROMPT)
        self.assertEqual(
            resolved["style"]["generation_settings"],
            {"cfg_scale": 6.0},
        )
        self.assertEqual(
            resolved["characters"][0]["negative"],
            "extra fingers",
        )
        self.assertEqual(resolved["characters"][0]["clothed"], "red coat")
        self.assertEqual(
            resolved["characters"][1],
            base["characters"][1],
        )
        self.assertEqual(
            resolved["setting"]["scene_values"]["include"],
            LONG_PROMPT,
        )
        self.assertEqual(
            resolved["setting"]["scene_values"]["background"],
            "train station",
        )
        self.assertEqual(
            resolved["generation"]["resolution"],
            {"width": 1024, "height": 1024},
        )
        self.assertEqual(
            resolved["generation"]["schedule"]["seed_policy"],
            {"mode": "fixed", "seed": 42},
        )
        self.assertEqual(
            resolved["future_blueprint_field"],
            {"preserve": True},
        )

    def test_background_outfit_carry_and_previous_result_vibe_continuity(self):
        previous_blueprint = self.base()
        previous_blueprint["setting"]["scene_values"]["background"] = "beach"
        previous_blueprint["characters"][0]["clothed"] = "swimsuit"
        previous_blueprint["characters"][1]["clothed"] = "linen shirt"
        previous_result = {
            "previous": {
                "blueprint": previous_blueprint,
                "artifact": {
                    "path": "output/previous.webp",
                    "sha256": "abc123",
                },
            },
        }
        previous_before = copy.deepcopy(previous_result)
        resolved = resolve_sequence_step(
            self.base(),
            self.plan(),
            "walk",
            previous_result,
        )

        self.assertEqual(previous_result, previous_before)
        self.assertEqual(
            resolved["setting"]["scene_values"]["background"],
            "beach",
        )
        self.assertEqual(
            [item["clothed"] for item in resolved["characters"]],
            ["swimsuit", "linen shirt"],
        )
        self.assertEqual(
            resolved["resources"]["vibes"][-1]["reference"],
            previous_result["previous"]["artifact"],
        )
        self.assertEqual(
            resolved["sequence"]["vibe_continuity"]["status"],
            "applied",
        )
        self.assertEqual(
            resolved["sequence"]["carried"],
            {
                "setting.scene_values.background": "previous-result",
                "characters:character:a:clothed": "previous-result",
                "characters:character:b:clothed": "previous-result",
            },
        )

    def test_first_and_last_vibe_sources_resolve_by_named_result(self):
        plan = self.plan()
        plan["steps"][1]["vibe_continuity"]["source"] = "first"
        results = {
            "first": {"image": {"path": "first.webp"}},
            "last": {"image": {"path": "last.webp"}},
        }
        first = resolve_sequence_step(self.base(), plan, "walk", results)
        self.assertEqual(
            first["resources"]["vibes"][-1]["reference"],
            {"path": "first.webp"},
        )

        plan["steps"][1]["vibe_continuity"]["source"] = "last"
        last = resolve_sequence_step(self.base(), plan, "walk", results)
        self.assertEqual(
            last["resources"]["vibes"][-1]["reference"],
            {"path": "last.webp"},
        )

    def test_invalid_progression_seed_vibe_direction_and_refs_are_rejected(self):
        with self.assertRaises(ValueError):
            canonical_sequence_plan({
                "progression": "forever",
                "steps": [],
            })
        with self.assertRaises(ValueError):
            canonical_sequence_plan({
                "steps": [{"seed_policy": {"mode": "fixed"}}],
            })
        with self.assertRaises(ValueError):
            canonical_sequence_plan({
                "steps": [{"vibe_continuity": {"source": "unknown"}}],
            })
        with self.assertRaises(ValueError):
            canonical_sequence_plan({
                "steps": [{"id": "one"}],
                "order": ["missing"],
            })
        with self.assertRaises(ValueError):
            next_sequence_step(self.plan(), "intro", "sideways")

        plan = self.plan()
        plan["steps"][0]["character_overrides"] = {
            "character:missing": {"negative": "x"},
        }
        with self.assertRaises(ValueError):
            resolve_sequence_step(self.base(), plan, "intro")


if __name__ == "__main__":
    unittest.main()
