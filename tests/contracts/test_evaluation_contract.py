# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import unittest

from src.nai_studio.domain.evaluation import (
    EVALUATION_SCHEMA,
    PROMOTION_TARGETS,
    REVIEW_STATES,
    canonical_evaluation,
    evaluation_id,
    fingerprint_evaluation,
    merge_evaluations,
    promote_result,
    record_blind_match,
    record_rating,
)


LONG_MEMO = (
    "동일 시드와 해상도에서 손 표현은 안정적이고, 배경 계보도 확인함. "
    "원문을 줄이거나 요약하지 말 것. 😀\n"
) * 180


class EvaluationContractTests(unittest.TestCase):
    def sample(self, suffix="one"):
        return {
            "favorite": True,
            "rating": 4.5,
            "memo": LONG_MEMO,
            "tags": ["인물", "검토 완료"],
            "review_state": "confirmed",
            "fixed_board": {
                "member": True,
                "boards": ["board:comparison"],
            },
            "blind": {
                "enabled": True,
                "revealed": False,
                "matches": 2,
            },
            "elo": {
                "rating": 1512.0,
                "matches": 2,
                "wins": 1,
                "losses": 1,
            },
            "evidence_refs": [f"evidence:style:{suffix}"],
            "result_refs": [f"result:{suffix}"],
            "asset_refs": [f"knowledge:style:{suffix}"],
            "future_field": {"uncertainty": 0.2},
        }

    def test_canonical_evaluation_preserves_all_fields_and_long_korean_memo(self):
        source = self.sample()
        before = copy.deepcopy(source)
        value = canonical_evaluation(source)

        self.assertEqual(source, before)
        self.assertEqual(value["schema"], EVALUATION_SCHEMA)
        self.assertEqual(value["memo"], LONG_MEMO)
        self.assertTrue(value["favorite"])
        self.assertEqual(value["rating"], 4.5)
        self.assertEqual(value["tags"], ["인물", "검토 완료"])
        self.assertEqual(value["review_state"], "confirmed")
        self.assertEqual(value["fixed_board"]["boards"], ["board:comparison"])
        self.assertEqual(value["blind"]["matches"], 2)
        self.assertEqual(value["future_field"], {"uncertainty": 0.2})

    def test_stable_id_uses_subject_refs_while_fingerprint_tracks_evaluation(self):
        first = self.sample()
        second = copy.deepcopy(first)
        second["updated_at"] = "2030-01-01T00:00:00Z"
        self.assertEqual(evaluation_id(first), evaluation_id(second))
        self.assertEqual(
            fingerprint_evaluation(first),
            fingerprint_evaluation(second),
        )

        second["rating"] = 2
        self.assertEqual(evaluation_id(first), evaluation_id(second))
        self.assertNotEqual(
            fingerprint_evaluation(first),
            fingerprint_evaluation(second),
        )

    def test_all_review_states_and_promotion_targets_are_supported(self):
        for state in REVIEW_STATES:
            value = self.sample()
            value["review_state"] = state
            self.assertEqual(canonical_evaluation(value)["review_state"], state)
        for target in PROMOTION_TARGETS:
            decision = promote_result(self.sample(), target)
            self.assertEqual(decision["target"], target)
            self.assertEqual(decision["status"], "proposed")
            self.assertFalse(decision["automatic"])
            self.assertEqual(
                decision["lineage"]["source_result_ref"],
                "result:one",
            )

    def test_record_rating_is_pure_and_keeps_previous_value(self):
        source = self.sample()
        before = copy.deepcopy(source)
        result = record_rating(source, 5)

        self.assertEqual(source, before)
        self.assertEqual(result["id"], evaluation_id(source))
        self.assertEqual(result["rating"], 5)
        self.assertEqual(
            result["rating_history"][-1],
            {"rating": 5, "previous": 4.5},
        )

    def test_blind_match_updates_elo_and_matches_without_mutating_players(self):
        winner = self.sample("winner")
        loser = self.sample("loser")
        winner["elo"] = {
            "rating": 1500,
            "matches": 0,
            "wins": 0,
            "losses": 0,
        }
        loser["elo"] = copy.deepcopy(winner["elo"])
        winner["blind"]["matches"] = 0
        loser["blind"]["matches"] = 0
        winner_before = copy.deepcopy(winner)
        loser_before = copy.deepcopy(loser)
        result = record_blind_match(winner, loser)

        self.assertEqual(winner, winner_before)
        self.assertEqual(loser, loser_before)
        self.assertEqual(result["winner"]["elo"]["rating"], 1516.0)
        self.assertEqual(result["loser"]["elo"]["rating"], 1484.0)
        self.assertEqual(result["winner"]["elo"]["matches"], 1)
        self.assertEqual(result["winner"]["elo"]["wins"], 1)
        self.assertEqual(result["loser"]["elo"]["losses"], 1)
        self.assertEqual(result["winner"]["blind"]["matches"], 1)

    def test_promotion_preserves_result_lineage_and_never_changes_source(self):
        source = self.sample()
        before = copy.deepcopy(source)
        decision = promote_result(source, "reference", result_ref="result:one")

        self.assertEqual(source, before)
        self.assertEqual(decision["schema"], "nai-promotion-decision/v1")
        self.assertEqual(
            decision["lineage"]["evaluation_id"],
            evaluation_id(source),
        )
        self.assertEqual(
            decision["lineage"]["evidence_refs"],
            source["evidence_refs"],
        )
        self.assertEqual(
            decision["lineage"]["asset_refs"],
            source["asset_refs"],
        )

    def test_merge_preserves_memos_tags_ratings_sources_and_reports_conflicts(self):
        first = self.sample("one")
        second = self.sample("two")
        second["favorite"] = False
        second["rating"] = 2
        second["memo"] = "두 번째 평가 원문\n삭제 금지"
        second["tags"] = ["검토 완료", "배경"]
        second["review_state"] = "shared"
        first_before = copy.deepcopy(first)
        second_before = copy.deepcopy(second)
        result = merge_evaluations(first, second)
        merged = result["evaluation"]

        self.assertEqual(first, first_before)
        self.assertEqual(second, second_before)
        self.assertEqual(merged["tags"], ["인물", "검토 완료", "배경"])
        self.assertEqual(
            [item["memo"] for item in merged["memo_entries"]],
            [LONG_MEMO, "두 번째 평가 원문\n삭제 금지"],
        )
        self.assertEqual(
            [item["rating"] for item in merged["rating_entries"]],
            [4.5, 2],
        )
        self.assertEqual(len(merged["merged_sources"]), 2)
        self.assertEqual(merged["review_state"], "shared")
        paths = {item["path"] for item in result["conflicts"]}
        self.assertTrue({"favorite", "rating", "memo", "review_state"} <= paths)

    def test_invalid_rating_refs_state_match_and_promotion_are_rejected(self):
        for rating in (-0.1, 5.1):
            with self.subTest(rating=rating):
                value = self.sample()
                value["rating"] = rating
                with self.assertRaises(ValueError):
                    canonical_evaluation(value)
        with self.assertRaises(ValueError):
            record_rating(self.sample(), 6)
        with self.assertRaises(ValueError):
            canonical_evaluation({
                "review_state": "published",
                "result_refs": ["result:one"],
            })
        with self.assertRaises(ValueError):
            canonical_evaluation({
                "result_refs": [""],
            })
        with self.assertRaises(ValueError):
            record_blind_match(self.sample(), self.sample())
        with self.assertRaises(ValueError):
            promote_result(self.sample(), "setting")
        with self.assertRaises(ValueError):
            promote_result(self.sample(), "style", result_ref="result:other")


if __name__ == "__main__":
    unittest.main()
