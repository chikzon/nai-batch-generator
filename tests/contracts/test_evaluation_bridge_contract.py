# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import unittest

from src.nai_studio.services.evaluation_bridge import (
    EVALUATION_EVENT_SCHEMA,
    append_evaluation_events,
    blind_match_event,
    fixed_board_event,
    lifecycle_event,
    present_blind_pair,
    project_legacy_evaluations,
    promotion_event,
)


LONG_MEMO = (
    "비교 manifest와 실제 결과를 함께 보고 남긴 한국어 메모. "
    "요약하거나 자르지 않는다. 😀\n"
) * 180


class EvaluationBridgeContractTests(unittest.TestCase):
    def picks(self):
        return {
            "picked": ["비교생성/run/a.webp"],
            "fav": ["비교생성/run/a.webp"],
            "folders": {
                "고정 6칸": [
                    "비교생성/run/a.webp",
                    "비교생성/run/b.webp",
                ],
            },
            "ranks": {"비교생성/run/a.webp": 1},
            "ratings": {
                "비교생성/run/a.webp": 5,
                "비교생성/run/b.webp": 3,
            },
            "elo": {
                "비교생성/run/a.webp": 1012.0,
                "비교생성/run/b.webp": 988.0,
            },
            "elo_matches": {
                "비교생성/run/a.webp": 2,
                "비교생성/run/b.webp": 2,
            },
            "tags": {
                "비교생성/run/a.webp": ["손 안정", "배경 좋음"],
            },
            # 현재 UI에는 없지만 옛/후속 필드가 있으면 원문을 잃지 않는다.
            "memos": {"비교생성/run/a.webp": LONG_MEMO},
            "review_states": {
                "비교생성/run/a.webp": "confirmed",
            },
            "future_pick_field": {"keep": True},
        }

    def manifest(self):
        return {
            "signature": "comparison-signature",
            "folder": "비교생성/run",
            "mode": "both",
            "completed": {
                "job-a": {
                    "file": "비교생성/run/a.webp",
                    "style": "화풍 A",
                    "character": "캐릭터 A",
                    "style_id": "style:a",
                    "character_id": "character:a",
                    "seed": 42,
                    "seed_index": 0,
                    "width": 832,
                    "height": 1216,
                },
                "job-b": {
                    "file": "비교생성/run/b.webp",
                    "style": "화풍 B",
                    "character": "캐릭터 B",
                    "style_id": "style:b",
                    "character_id": "character:b",
                    "seed": 42,
                    "seed_index": 0,
                    "width": 832,
                    "height": 1216,
                },
            },
        }

    def projected(self):
        return project_legacy_evaluations(
            self.picks(),
            comparison_manifests=[self.manifest()],
            result_records=[
                {
                    "path": "비교생성/run/a.webp",
                    "tags": ["배경 좋음", "보존"],
                    "memo": "결과 파일 메모 원문",
                    "evidence_refs": ["evidence:generation:a"],
                },
                {
                    "path": "비교생성/run/b.webp",
                    "evidence_refs": ["evidence:generation:b"],
                },
            ],
        )

    def test_projects_picks_manifest_and_results_losslessly_without_mutation(self):
        picks = self.picks()
        manifest = self.manifest()
        results = [
            {
                "path": "비교생성/run/a.webp",
                "tags": ["배경 좋음", "보존"],
                "memo": "결과 파일 메모 원문",
                "evidence_refs": ["evidence:generation:a"],
            },
        ]
        before = (copy.deepcopy(picks), copy.deepcopy(manifest), copy.deepcopy(results))
        projected = project_legacy_evaluations(
            picks,
            comparison_manifests=[manifest],
            result_records=results,
        )

        self.assertEqual((picks, manifest, results), before)
        values = {
            item["subject"]["path"]: item
            for item in projected["evaluations"]
        }
        first = values["비교생성/run/a.webp"]
        self.assertTrue(first["favorite"])
        self.assertEqual(first["rating"], 5)
        self.assertEqual(first["memo"], LONG_MEMO)
        self.assertEqual(
            [item["memo"] for item in first["memo_entries"]],
            [LONG_MEMO, "결과 파일 메모 원문"],
        )
        self.assertEqual(
            first["tags"],
            ["손 안정", "배경 좋음", "보존"],
        )
        self.assertEqual(first["review_state"], "confirmed")
        self.assertEqual(
            first["fixed_board"],
            {"member": True, "boards": ["고정 6칸"]},
        )
        self.assertEqual(first["elo"]["rating"], 1012.0)
        self.assertEqual(first["elo"]["matches"], 2)
        self.assertEqual(
            first["comparison_lineage"]["job_key"],
            "job-a",
        )
        self.assertEqual(
            first["evidence_refs"],
            ["evidence:generation:a"],
        )
        self.assertEqual(first["legacy_rank"], 1)

    def test_rating_and_lifecycle_disagreement_is_preserved_as_issue(self):
        manifest = self.manifest()
        manifest["completed"]["job-a"]["rating"] = 2
        manifest["completed"]["job-a"]["review_state"] = "shared"
        projected = project_legacy_evaluations(
            self.picks(),
            comparison_manifests=[manifest],
        )
        first = next(
            item for item in projected["evaluations"]
            if item["subject"]["path"].endswith("a.webp")
        )
        self.assertEqual(first["rating"], 5)
        self.assertEqual(first["review_state"], "shared")
        self.assertEqual(
            {item["code"] for item in projected["issues"]},
            {"rating-conflict", "review-state-conflict"},
        )
        self.assertEqual(
            [item["rating"] for item in first["rating_entries"]],
            [5, 2],
        )

    def test_blind_pair_prefers_least_matches_then_nearest_elo_and_hides_labels(self):
        evaluations = self.projected()["evaluations"]
        third = project_legacy_evaluations({
            "elo": {"other/c.webp": 1010},
            "elo_matches": {"other/c.webp": 0},
        })["evaluations"][0]
        pair = present_blind_pair([*evaluations, third])

        self.assertTrue(pair["blind"])
        self.assertTrue(pair["a"]["result_ref"].endswith("other/c.webp"))
        self.assertIn("rating", pair["hidden_fields"])
        self.assertNotIn("name", pair["a"])
        self.assertNotIn("elo", pair["a"])

    def test_blind_match_event_uses_legacy_k24_and_is_append_only(self):
        evaluations = self.projected()["evaluations"]
        winner, loser = evaluations[0], evaluations[1]
        picks = self.picks()
        before = copy.deepcopy(picks)
        event = blind_match_event(winner, loser)
        appended = append_evaluation_events(picks, [event])

        self.assertEqual(picks, before)
        self.assertEqual(event["schema"], EVALUATION_EVENT_SCHEMA)
        self.assertEqual(event["kind"], "blind-match")
        self.assertEqual(event["payload"]["k_factor"], 24.0)
        projection = event["payload"]["legacy_projection"]
        self.assertEqual(
            projection["비교생성/run/a.webp"]["elo_matches"],
            3,
        )
        self.assertTrue(appended["append_only"])
        self.assertEqual(
            appended["picks"]["ratings"],
            picks["ratings"],
        )
        self.assertEqual(
            appended["picks"]["tags"],
            picks["tags"],
        )
        self.assertEqual(len(appended["picks"]["evaluation_events"]), 1)

    def test_blind_tie_updates_both_match_counts_without_winner(self):
        first, second = self.projected()["evaluations"]
        event = blind_match_event(first, second, outcome="tie")
        projection = event["payload"]["legacy_projection"]

        self.assertEqual(event["payload"]["outcome"], "tie")
        self.assertEqual(
            projection["비교생성/run/a.webp"]["elo_matches"],
            3,
        )
        self.assertEqual(
            projection["비교생성/run/b.webp"]["elo_matches"],
            3,
        )
        self.assertLess(
            projection["비교생성/run/a.webp"]["elo"],
            first["elo"]["rating"],
        )
        self.assertGreater(
            projection["비교생성/run/b.webp"]["elo"],
            second["elo"]["rating"],
        )

    def test_board_lifecycle_and_promotion_are_only_events_with_lineage(self):
        evaluation = self.projected()["evaluations"][0]
        events = [
            fixed_board_event(evaluation, "최종 후보"),
            lifecycle_event(evaluation, "shared"),
            promotion_event(evaluation, "style"),
        ]
        result = append_evaluation_events(self.picks(), events)

        self.assertEqual(
            [item["kind"] for item in result["picks"]["evaluation_events"]],
            ["fixed-board", "lifecycle", "promotion-proposed"],
        )
        promotion = events[-1]["payload"]["decision"]
        self.assertFalse(promotion["automatic"])
        self.assertEqual(
            promotion["lineage"]["source_result_ref"],
            "result:비교생성/run/a.webp",
        )
        self.assertEqual(
            events[1]["payload"]["from"],
            "confirmed",
        )
        self.assertEqual(events[1]["payload"]["to"], "shared")

    def test_duplicate_event_is_not_appended_twice(self):
        evaluation = self.projected()["evaluations"][0]
        event = lifecycle_event(evaluation, "confirmed")
        first = append_evaluation_events(self.picks(), [event])
        second = append_evaluation_events(first["picks"], [event])

        self.assertEqual(len(second["picks"]["evaluation_events"]), 1)
        self.assertEqual(second["appended"], [])
        self.assertEqual(second["duplicates"], [event["id"]])

    def test_invalid_pair_board_lifecycle_and_event_are_rejected(self):
        evaluation = self.projected()["evaluations"][0]
        with self.assertRaises(ValueError):
            present_blind_pair([evaluation])
        with self.assertRaises(ValueError):
            fixed_board_event(evaluation, "")
        with self.assertRaises(ValueError):
            lifecycle_event(evaluation, "published")
        with self.assertRaises(ValueError):
            blind_match_event(evaluation, evaluation, outcome="tie")
        with self.assertRaises(ValueError):
            blind_match_event(
                evaluation,
                self.projected()["evaluations"][1],
                outcome="draw",
            )
        with self.assertRaises(ValueError):
            append_evaluation_events(self.picks(), [{"kind": "broken"}])


if __name__ == "__main__":
    unittest.main()
