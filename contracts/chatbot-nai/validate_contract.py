# -*- coding: utf-8 -*-
"""표준 라이브러리만 쓰는 챗봇↔NAI 계약 검증기.

JSON Schema는 외부 구현과 문서를 위한 원본이고, 이 파일은 설치 의존성을 늘리지
않으면서 두 앱의 경계에서 즉시 거절해야 할 오류를 검사한다.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
FORBIDDEN_KEYS = {
    "token",
    "api_token",
    "authorization",
    "prompt",
    "negative_prompt",
    "image",
    "image_base64",
    "base64",
}


class ContractError(ValueError):
    pass


def _object(value, path):
    if not isinstance(value, dict):
        raise ContractError(f"{path}: 객체가 필요합니다.")
    return value


def _array(value, path, maximum=None):
    if not isinstance(value, list):
        raise ContractError(f"{path}: 배열이 필요합니다.")
    if maximum is not None and len(value) > maximum:
        raise ContractError(f"{path}: 최대 {maximum}개입니다.")
    return value


def _only(data, allowed, path):
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise ContractError(f"{path}: 알 수 없는 필드 {', '.join(unknown)}")


def _required(data, names, path):
    missing = [name for name in names if name not in data]
    if missing:
        raise ContractError(f"{path}: 필수 필드 누락 {', '.join(missing)}")


def _id(value, path):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ContractError(f"{path}: 유효하지 않은 ID입니다.")
    return value


def _integer(value, path, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{path}: 정수가 필요합니다.")
    if minimum is not None and value < minimum:
        raise ContractError(f"{path}: {minimum} 이상이어야 합니다.")
    if maximum is not None and value > maximum:
        raise ContractError(f"{path}: {maximum} 이하여야 합니다.")
    return value


def _reject_private_payload(value, path="$"):
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                raise ContractError(f"{path}.{key}: 연결 계약에 넣을 수 없는 필드입니다.")
            _reject_private_payload(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_private_payload(child, f"{path}[{index}]")


def _validate_cast(rows):
    seen = set()
    for index, raw in enumerate(_array(rows, "$.context.cast", 6)):
        path = f"$.context.cast[{index}]"
        row = _object(raw, path)
        _required(row, ["character_id"], path)
        _only(row, ["character_id", "outfit_id", "action_id", "emotion_id"], path)
        character_id = _id(row["character_id"], f"{path}.character_id")
        if character_id in seen:
            raise ContractError(f"{path}.character_id: 중복 캐릭터입니다.")
        seen.add(character_id)
        for name in ("outfit_id", "action_id", "emotion_id"):
            if name in row:
                _id(row[name], f"{path}.{name}")
    return seen


def _validate_nai_characters(rows):
    seen = set()
    for index, raw in enumerate(_array(rows, "$.nai_refs.characters", 6)):
        path = f"$.nai_refs.characters[{index}]"
        row = _object(raw, path)
        _required(row, ["character_id", "preset_id"], path)
        _only(
            row,
            ["character_id", "preset_id", "reference_ids", "vibe_ids"],
            path,
        )
        character_id = _id(row["character_id"], f"{path}.character_id")
        _id(row["preset_id"], f"{path}.preset_id")
        if character_id in seen:
            raise ContractError(f"{path}.character_id: 중복 캐릭터입니다.")
        seen.add(character_id)
        for name in ("reference_ids", "vibe_ids"):
            values = row.get(name, [])
            ids = [_id(value, f"{path}.{name}") for value in _array(values, f"{path}.{name}")]
            if len(ids) != len(set(ids)):
                raise ContractError(f"{path}.{name}: 중복 ID가 있습니다.")
    return seen


def validate_render_request(data):
    data = _object(data, "$")
    _required(
        data,
        [
            "contract_version",
            "request_id",
            "project_id",
            "scene_id",
            "context",
            "nai_refs",
            "generation",
            "output",
        ],
        "$",
    )
    _only(
        data,
        [
            "contract_version",
            "request_id",
            "project_id",
            "scene_id",
            "context",
            "nai_refs",
            "generation",
            "output",
        ],
        "$",
    )
    if data["contract_version"] != "render-request/v1":
        raise ContractError("$.contract_version: render-request/v1이 필요합니다.")
    for name in ("request_id", "project_id", "scene_id"):
        _id(data[name], f"$.{name}")

    context = _object(data["context"], "$.context")
    _required(context, ["location_id", "cast"], "$.context")
    _only(context, ["location_id", "time_id", "cast"], "$.context")
    _id(context["location_id"], "$.context.location_id")
    if "time_id" in context:
        _id(context["time_id"], "$.context.time_id")
    cast_ids = _validate_cast(context["cast"])

    refs = _object(data["nai_refs"], "$.nai_refs")
    _required(refs, ["style_id", "setting_id", "characters"], "$.nai_refs")
    _only(
        refs,
        ["style_id", "setting_id", "setting_scene_id", "characters"],
        "$.nai_refs",
    )
    _id(refs["style_id"], "$.nai_refs.style_id")
    _id(refs["setting_id"], "$.nai_refs.setting_id")
    if "setting_scene_id" in refs:
        _id(refs["setting_scene_id"], "$.nai_refs.setting_scene_id")
    nai_character_ids = _validate_nai_characters(refs["characters"])
    if cast_ids != nai_character_ids:
        raise ContractError("$.nai_refs.characters: context.cast와 캐릭터 ID가 같아야 합니다.")

    generation = _object(data["generation"], "$.generation")
    _required(generation, ["width", "height", "count", "seed_mode"], "$.generation")
    _only(generation, ["width", "height", "count", "seed_mode", "seed"], "$.generation")
    for name in ("width", "height"):
        value = _integer(generation[name], f"$.generation.{name}", 64, 2048)
        if value % 64:
            raise ContractError(f"$.generation.{name}: 64의 배수여야 합니다.")
    _integer(generation["count"], "$.generation.count", 1, 10000)
    if generation["seed_mode"] not in {"random", "fixed", "sequence"}:
        raise ContractError("$.generation.seed_mode: 지원하지 않는 방식입니다.")
    if generation["seed_mode"] in {"fixed", "sequence"} and "seed" not in generation:
        raise ContractError("$.generation.seed: fixed/sequence에는 seed가 필요합니다.")
    if "seed" in generation:
        _integer(generation["seed"], "$.generation.seed", 0, 4294967295)

    output = _object(data["output"], "$.output")
    _required(output, ["logical_name", "preserve_exif"], "$.output")
    _only(
        output,
        ["logical_name", "preserve_exif", "postprocess", "r2_key_candidate"],
        "$.output",
    )
    if not isinstance(output["logical_name"], str) or not output["logical_name"].strip():
        raise ContractError("$.output.logical_name: 빈 이름은 허용하지 않습니다.")
    if not isinstance(output["preserve_exif"], bool):
        raise ContractError("$.output.preserve_exif: boolean이 필요합니다.")
    postprocess = _array(output.get("postprocess", []), "$.output.postprocess")
    allowed = {"background_remove", "composite", "censor"}
    if any(item not in allowed for item in postprocess):
        raise ContractError("$.output.postprocess: 지원하지 않는 후처리입니다.")
    if len(postprocess) != len(set(postprocess)):
        raise ContractError("$.output.postprocess: 중복 후처리가 있습니다.")
    _reject_private_payload(data)
    return data


def validate_render_result(data):
    data = _object(data, "$")
    _required(
        data,
        ["contract_version", "request_id", "status", "retryable", "artifacts"],
        "$",
    )
    _only(
        data,
        [
            "contract_version",
            "request_id",
            "status",
            "retryable",
            "error",
            "artifacts",
            "reproduction",
            "publish",
        ],
        "$",
    )
    if data["contract_version"] != "render-result/v1":
        raise ContractError("$.contract_version: render-result/v1이 필요합니다.")
    _id(data["request_id"], "$.request_id")
    status = data["status"]
    if status not in {"queued", "running", "succeeded", "failed", "cancelled"}:
        raise ContractError("$.status: 지원하지 않는 상태입니다.")
    if not isinstance(data["retryable"], bool):
        raise ContractError("$.retryable: boolean이 필요합니다.")

    artifacts = _array(data["artifacts"], "$.artifacts")
    for index, raw in enumerate(artifacts):
        path = f"$.artifacts[{index}]"
        row = _object(raw, path)
        _required(row, ["artifact_id", "sha256", "width", "height"], path)
        _only(
            row,
            ["artifact_id", "local_path", "url", "sha256", "width", "height", "seed"],
            path,
        )
        _id(row["artifact_id"], f"{path}.artifact_id")
        if "local_path" not in row and "url" not in row:
            raise ContractError(f"{path}: local_path 또는 url이 필요합니다.")
        if not isinstance(row["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"]):
            raise ContractError(f"{path}.sha256: 소문자 SHA-256이 필요합니다.")
        _integer(row["width"], f"{path}.width", 1)
        _integer(row["height"], f"{path}.height", 1)
        if "seed" in row:
            _integer(row["seed"], f"{path}.seed", 0, 4294967295)

    if status == "succeeded":
        if not artifacts:
            raise ContractError("$.artifacts: 성공 결과에는 파일이 필요합니다.")
        reproduction = _object(data.get("reproduction"), "$.reproduction")
        _required(
            reproduction,
            ["style_id", "setting_id", "character_ids", "actual_settings"],
            "$.reproduction",
        )
        _only(
            reproduction,
            ["style_id", "setting_id", "character_ids", "actual_settings"],
            "$.reproduction",
        )
        _id(reproduction["style_id"], "$.reproduction.style_id")
        _id(reproduction["setting_id"], "$.reproduction.setting_id")
        for value in _array(reproduction["character_ids"], "$.reproduction.character_ids", 6):
            _id(value, "$.reproduction.character_ids")
        _object(reproduction["actual_settings"], "$.reproduction.actual_settings")
    if status == "failed":
        error = _object(data.get("error"), "$.error")
        _required(error, ["code", "message"], "$.error")
        _only(error, ["code", "message"], "$.error")
        _id(error["code"], "$.error.code")
        if not isinstance(error["message"], str) or not error["message"].strip():
            raise ContractError("$.error.message: 빈 오류 메시지는 허용하지 않습니다.")
    _reject_private_payload(data)
    return data


def validate_asset_map(data):
    data = _object(data, "$")
    _required(data, ["contract_version", "revision", "characters", "locations"], "$")
    _only(data, ["contract_version", "revision", "characters", "locations"], "$")
    if data["contract_version"] != "asset-map/v1":
        raise ContractError("$.contract_version: asset-map/v1이 필요합니다.")
    _integer(data["revision"], "$.revision", 1)
    for group, required_id, optional_id in (
        ("characters", "nai_character_id", "default_outfit_id"),
        ("locations", "background_asset_id", "nai_setting_id"),
    ):
        rows = _object(data[group], f"$.{group}")
        for source_id, raw in rows.items():
            _id(source_id, f"$.{group} key")
            path = f"$.{group}.{source_id}"
            row = _object(raw, path)
            _required(row, [required_id], path)
            _only(row, [required_id, optional_id], path)
            _id(row[required_id], f"{path}.{required_id}")
            if optional_id in row:
                _id(row[optional_id], f"{path}.{optional_id}")
    _reject_private_payload(data)
    return data


def validate_document(data):
    version = data.get("contract_version") if isinstance(data, dict) else None
    if version == "render-request/v1":
        return validate_render_request(data)
    if version == "render-result/v1":
        return validate_render_result(data)
    if version == "asset-map/v1":
        return validate_asset_map(data)
    raise ContractError("$.contract_version: 알 수 없는 계약 버전입니다.")


def main(argv=None):
    paths = [Path(value) for value in (argv if argv is not None else sys.argv[1:])]
    if not paths:
        raise SystemExit("사용법: python validate_contract.py 파일.json [...]")
    failed = False
    for path in paths:
        try:
            validate_document(json.loads(path.read_text(encoding="utf-8")))
            print(f"OK {path}")
        except (OSError, json.JSONDecodeError, ContractError) as exc:
            failed = True
            print(f"FAIL {path}: {exc}", file=sys.stderr)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()

