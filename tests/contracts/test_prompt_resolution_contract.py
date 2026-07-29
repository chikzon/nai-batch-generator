# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.nai_studio.domain.prompt_resolution import (  # noqa: E402
    MAX_DEPTH,
    MAX_OUTPUT_LENGTH,
    CyclicFragmentError,
    FrozenChoiceError,
    MissingFragmentError,
    PromptDepthError,
    PromptOutputLimitError,
    PromptResolutionError,
    reroll_components,
    resolve_prompt,
)


class PromptResolutionContractTests(unittest.TestCase):
    def test_same_seed_is_deterministic_and_preserves_nai_syntax(self):
        template = (
            "1.2::{붉은색|푸른색} dress::, <표정>, ||red||, "
            "<|> 배경 <|>, <*차례>, {|_|}, 끝"
        )
        fragments = {
            "표정": ["미소", "{졸린|화난} 표정"],
        }
        first = resolve_prompt(template, fragments, 77)
        second = resolve_prompt(template, fragments, 77)
        self.assertEqual(first, second)
        self.assertIn("1.2::", first["text"])
        self.assertIn("::", first["text"])
        self.assertIn("||red||", first["text"])
        self.assertIn("<|> 배경 <|>", first["text"])
        self.assertIn("<*차례>", first["text"])
        self.assertIn("{|_|}", first["text"])
        self.assertTrue(first["text"].endswith(", 끝"))

    def test_components_have_stable_source_ranges_choices_and_trace(self):
        template = "앞 {가|나} 중간 <색> 뒤"
        result = resolve_prompt(template, {"색": ["red", "blue"]}, 9)
        self.assertEqual(len(result["components"]), 2)
        inline, fragment = result["components"]
        self.assertEqual(
            template[inline["range"]["start"]:inline["range"]["end"]],
            "{가|나}",
        )
        self.assertEqual(
            template[fragment["range"]["start"]:fragment["range"]["end"]],
            "<색>",
        )
        self.assertEqual(inline["source"], {"kind": "template", "name": ""})
        self.assertEqual(fragment["fragment"], "색")
        self.assertIn(inline["choice"]["value"], ("가", "나"))
        self.assertIn(fragment["choice"]["value"], ("red", "blue"))
        self.assertEqual(
            {item["component_id"] for item in result["trace"]},
            {inline["id"], fragment["id"]},
        )
        for item in result["components"]:
            span = item["output_range"]
            self.assertEqual(
                result["text"][span["start"]:span["end"]],
                resolve_prompt(
                    item["choice"]["value"], {"색": ["red", "blue"]}, 9
                )["text"],
            )

    def test_nested_fragment_and_inline_components_are_traced(self):
        result = resolve_prompt(
            "인물 <외형>",
            {
                "외형": ["<머리>, {교복|드레스}"],
                "머리": ["긴 머리", "짧은 머리"],
            },
            3,
        )
        self.assertNotIn("<", result["text"])
        self.assertNotIn("{", result["text"])
        self.assertEqual(len(result["components"]), 3)
        outer = result["components"][0]
        children = result["components"][1:]
        self.assertTrue(all(item["parent_id"] == outer["id"]
                            for item in children))
        self.assertEqual({item["depth"] for item in children}, {1})

    def test_freeze_keeps_every_choice_with_a_different_seed(self):
        first = resolve_prompt(
            "{a|b|c}, <색>, {x|y}",
            {"색": ["red", "green", "blue"]},
            1,
        )
        frozen = resolve_prompt(
            first["inputs"]["template"],
            first["inputs"]["fragments"],
            999999,
            frozen=first["freeze"],
        )
        self.assertEqual(frozen["text"], first["text"])
        self.assertEqual(
            [item["choice"]["value"] for item in frozen["components"]],
            [item["choice"]["value"] for item in first["components"]],
        )
        self.assertTrue(all(item["choice"]["frozen"]
                            for item in frozen["components"]))

    def test_partial_reroll_changes_only_selected_component(self):
        first = resolve_prompt(
            "시작 {red|blue|green} / <표정> / {day|night} 끝",
            {"표정": ["smile", "angry", "sleepy"]},
            11,
        )
        selected = first["components"][1]["id"]
        rerolled = reroll_components(first, [selected], 22)
        before = {item["id"]: item for item in first["components"]}
        after = {item["id"]: item for item in rerolled["components"]}

        self.assertNotEqual(
            after[selected]["choice"]["value"],
            before[selected]["choice"]["value"],
        )
        for identifier in (first["components"][0]["id"],
                           first["components"][2]["id"]):
            self.assertEqual(
                after[identifier]["choice"]["value"],
                before[identifier]["choice"]["value"],
            )
            self.assertTrue(after[identifier]["choice"]["frozen"])
        before_parts = first["text"].split(" / ")
        after_parts = rerolled["text"].split(" / ")
        self.assertEqual(before_parts[0], after_parts[0])
        self.assertEqual(before_parts[2], after_parts[2])

    def test_missing_cycle_depth_and_output_limits_raise_without_truncation(self):
        with self.assertRaises(MissingFragmentError):
            resolve_prompt("before <없음> after", {}, 1)
        with self.assertRaises(CyclicFragmentError):
            resolve_prompt("<A>", {"A": ["<B>"], "B": ["<A>"]}, 1)

        nested_fragments = {
            f"단계{index}": [f"<단계{index + 1}>"]
            for index in range(MAX_DEPTH + 1)
        }
        nested_fragments[f"단계{MAX_DEPTH + 1}"] = ["끝"]
        with self.assertRaises(PromptDepthError):
            resolve_prompt("<단계0>", nested_fragments, 1)

        oversized = "한" * (MAX_OUTPUT_LENGTH + 1)
        with self.assertRaises(PromptOutputLimitError):
            resolve_prompt(oversized, {}, 1)

    def test_stale_freeze_and_unknown_reroll_ids_are_explicit_errors(self):
        first = resolve_prompt("{a|b}", {}, 1)
        changed = copy.deepcopy(first["freeze"])
        changed["template_hash"] = "0" * 64
        with self.assertRaises(FrozenChoiceError):
            resolve_prompt("{a|b}", {}, 1, frozen=changed)
        with self.assertRaises(PromptResolutionError):
            reroll_components(first, ["component-missing"], 2)

    def test_inputs_are_never_modified(self):
        template = "한글 <색>, {낮|밤}"
        fragments = {"색": ["빨강", "{파랑|초록}"]}
        before_fragments = copy.deepcopy(fragments)
        frozen_source = resolve_prompt(template, fragments, 5)
        before_frozen = copy.deepcopy(frozen_source["freeze"])
        resolve_prompt(template, fragments, 6, frozen=frozen_source["freeze"])
        reroll_components(
            frozen_source, [frozen_source["components"][0]["id"]], 7)
        self.assertEqual(fragments, before_fragments)
        self.assertEqual(frozen_source["freeze"], before_frozen)


if __name__ == "__main__":
    unittest.main()
