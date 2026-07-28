# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "contracts" / "chatbot-nai"
V1 = CONTRACT_ROOT / "v1"
SPEC = importlib.util.spec_from_file_location(
    "chatbot_nai_contract_validator",
    CONTRACT_ROOT / "validate_contract.py",
)
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def fixture(name):
    return json.loads((V1 / "fixtures" / name).read_text(encoding="utf-8"))


class ChatbotNaiContractTests(unittest.TestCase):
    def test_json_schemas_and_valid_fixtures_parse(self):
        for name in (
            "render-request.schema.json",
            "render-result.schema.json",
            "asset-map.schema.json",
            "fixtures/valid-request.json",
            "fixtures/valid-result.json",
            "fixtures/valid-asset-map.json",
        ):
            self.assertIsInstance(
                json.loads((V1 / name).read_text(encoding="utf-8")),
                dict,
                name,
            )

    def test_valid_request_result_and_asset_map(self):
        VALIDATOR.validate_document(fixture("valid-request.json"))
        VALIDATOR.validate_document(fixture("valid-result.json"))
        VALIDATOR.validate_document(fixture("valid-asset-map.json"))

    def test_token_and_prompt_payloads_are_rejected_everywhere(self):
        request = fixture("valid-request.json")
        request["nai_refs"]["token"] = "must-not-cross-boundary"
        with self.assertRaises(VALIDATOR.ContractError):
            VALIDATOR.validate_document(request)

        result = fixture("valid-result.json")
        result["reproduction"]["actual_settings"]["prompt"] = "private"
        with self.assertRaises(VALIDATOR.ContractError):
            VALIDATOR.validate_document(result)

    def test_cast_and_nai_character_ids_must_match(self):
        request = fixture("valid-request.json")
        request["nai_refs"]["characters"][0]["character_id"] = "character:other"
        with self.assertRaises(VALIDATOR.ContractError):
            VALIDATOR.validate_render_request(request)

    def test_fixed_or_sequence_seed_requires_seed(self):
        for mode in ("fixed", "sequence"):
            request = fixture("valid-request.json")
            request["generation"]["seed_mode"] = mode
            del request["generation"]["seed"]
            with self.assertRaises(VALIDATOR.ContractError):
                VALIDATOR.validate_render_request(request)

    def test_random_seed_may_be_omitted(self):
        request = fixture("valid-request.json")
        request["generation"]["seed_mode"] = "random"
        del request["generation"]["seed"]
        VALIDATOR.validate_render_request(request)

    def test_success_needs_artifact_and_reproduction(self):
        result = fixture("valid-result.json")
        result["artifacts"] = []
        with self.assertRaises(VALIDATOR.ContractError):
            VALIDATOR.validate_render_result(result)

        result = fixture("valid-result.json")
        del result["reproduction"]
        with self.assertRaises(VALIDATOR.ContractError):
            VALIDATOR.validate_render_result(result)

    def test_failed_result_needs_error(self):
        result = fixture("valid-result.json")
        result["status"] = "failed"
        result["artifacts"] = []
        result.pop("reproduction")
        with self.assertRaises(VALIDATOR.ContractError):
            VALIDATOR.validate_render_result(result)

        result["error"] = {"code": "nai:temporary", "message": "temporary failure"}
        result["retryable"] = True
        VALIDATOR.validate_render_result(result)

    def test_unknown_fields_are_rejected(self):
        request = fixture("valid-request.json")
        request["generation"]["model"] = "belongs-to-nai-studio"
        with self.assertRaises(VALIDATOR.ContractError):
            VALIDATOR.validate_render_request(request)

    def test_validation_does_not_modify_input(self):
        request = fixture("valid-request.json")
        before = copy.deepcopy(request)
        VALIDATOR.validate_render_request(request)
        self.assertEqual(request, before)


if __name__ == "__main__":
    unittest.main()

