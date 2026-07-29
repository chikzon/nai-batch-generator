# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.nai_studio.services.prompt_bridge import (  # noqa: E402
    BRIDGE_SCHEMA,
    UI_STATE_SCHEMA,
    PromptBridgeError,
    legacy_sequence_text,
    prompt_ui_state,
    reroll_legacy_components,
    resolve_legacy_prompt,
)


class PromptBridgeContractTests(unittest.TestCase):
    def test_canonical_choices_resolve_but_sequential_counter_stays_legacy(self):
        template = (
            "1.2::{red|blue} dress::, <표정>, <*순차표정>, "
            "||red||, <|> mix <|>, {|_|}"
        )
        result = resolve_legacy_prompt(
            template,
            {
                "표정": ["smile", "angry"],
                "순차표정": ["first", "second"],
            },
            7,
        )
        self.assertEqual(result["schema"], BRIDGE_SCHEMA)
        self.assertNotIn("{red|blue}", result["text"])
        self.assertNotIn("<표정>", result["text"])
        self.assertIn("<*순차표정>", result["text"])
        self.assertIn("1.2::", result["text"])
        self.assertIn("||red||", result["text"])
        self.assertIn("<|> mix <|>", result["text"])
        self.assertIn("{|_|}", result["text"])
        self.assertTrue(result["legacy_sequence"]["pending"])
        self.assertTrue(result["legacy_sequence"]["pass_to_legacy"])
        reference = result["legacy_sequence"]["references"][0]
        self.assertEqual(reference["name"], "순차표정")
        self.assertEqual(
            result["text"][reference["range"]["start"]:reference["range"]["end"]],
            "<*순차표정>",
        )
        self.assertEqual(legacy_sequence_text(result), result["text"])

    def test_freeze_and_trace_are_json_safe_ui_state_without_duplicate_inputs(self):
        result = resolve_legacy_prompt(
            "{a|b}, <색>", {"색": ["red", "blue"]}, 1)
        state = result["ui_state"]
        self.assertEqual(state["schema"], UI_STATE_SCHEMA)
        self.assertEqual(state, prompt_ui_state(result))
        self.assertTrue(state["components"])
        self.assertTrue(state["trace"])
        self.assertIn("freeze", state)
        self.assertNotIn("inputs", state)
        self.assertNotIn("template", state)
        self.assertNotIn("fragments", state)
        encoded = json.dumps(state, ensure_ascii=False)
        self.assertNotIn("token", encoded.lower())
        self.assertNotIn("authorization", encoded.lower())

    def test_ui_freeze_replays_all_choices_with_different_seed(self):
        first = resolve_legacy_prompt(
            "{a|b|c}, <색>, <*순서>",
            {"색": ["red", "green", "blue"], "순서": ["one", "two"]},
            3,
        )
        replayed = resolve_legacy_prompt(
            first["canonical"]["inputs"]["template"],
            first["canonical"]["inputs"]["fragments"],
            9999,
            frozen=first["ui_state"]["freeze"],
        )
        self.assertEqual(replayed["text"], first["text"])
        self.assertEqual(
            replayed["legacy_sequence"]["references"],
            first["legacy_sequence"]["references"],
        )
        self.assertTrue(all(
            item["choice"]["frozen"]
            for item in replayed["canonical"]["components"]
        ))

    def test_partial_reroll_keeps_other_choices_and_legacy_placeholder(self):
        first = resolve_legacy_prompt(
            "{red|green|blue} / <표정> / {day|night} / <*순서>",
            {"표정": ["smile", "angry"], "순서": ["one", "two"]},
            11,
        )
        selected = first["canonical"]["components"][1]["id"]
        rerolled = reroll_legacy_components(first, [selected], 22)
        before = {
            item["id"]: item for item in first["canonical"]["components"]
        }
        after = {
            item["id"]: item for item in rerolled["canonical"]["components"]
        }
        self.assertNotEqual(
            after[selected]["choice"]["value"],
            before[selected]["choice"]["value"],
        )
        for identifier in (
            first["canonical"]["components"][0]["id"],
            first["canonical"]["components"][2]["id"],
        ):
            self.assertEqual(
                after[identifier]["choice"]["value"],
                before[identifier]["choice"]["value"],
            )
        self.assertIn("<*순서>", rerolled["text"])
        self.assertEqual(
            rerolled["legacy_sequence"]["references"][0]["name"], "순서")

    def test_long_prompt_is_not_truncated_and_source_objects_are_unchanged(self):
        prefix = "1.2::" + ("긴원문, " * 1300) + "::"
        template = prefix + " {낮|밤}, <색>, <*순서>, 끝"
        fragments = {
            "색": ["빨강", "파랑"],
            "순서": ["첫째", "둘째"],
        }
        before_fragments = copy.deepcopy(fragments)
        result = resolve_legacy_prompt(template, fragments, 17)
        self.assertTrue(result["text"].startswith(prefix))
        self.assertTrue(result["text"].endswith(", <*순서>, 끝"))
        self.assertGreater(len(result["text"]), 6000)
        self.assertEqual(fragments, before_fragments)
        self.assertEqual(template, prefix + " {낮|밤}, <색>, <*순서>, 끝")

    def test_bridge_helpers_reject_unrelated_objects(self):
        with self.assertRaises(PromptBridgeError):
            prompt_ui_state({"schema": "other"})
        with self.assertRaises(PromptBridgeError):
            legacy_sequence_text({"schema": "other"})

    def test_calls_do_not_mutate_result_or_freeze(self):
        first = resolve_legacy_prompt("{a|b}, <색>", {"색": ["r", "g"]}, 1)
        before = copy.deepcopy(first)
        prompt_ui_state(first)
        reroll_legacy_components(
            first, [first["canonical"]["components"][0]["id"]], 2)
        self.assertEqual(first, before)


if __name__ == "__main__":
    unittest.main()
