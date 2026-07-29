# -*- coding: utf-8 -*-
"""생성 전 비용과 최종 프롬프트 토큰을 계산하는 응용 서비스."""

from __future__ import annotations

import hashlib
import random
from typing import Any


def _balance(
    application: Any,
    operations: Any,
    requested: bool,
) -> tuple[dict | None, dict | None]:
    """계정별 잔액 캐시는 ConfigServer 잠금과 연결해 토큰 교체 시 섞이지 않게 한다."""
    token = str(application.cfg.get("token") or "")
    token_key = (
        hashlib.sha256(token.encode("utf-8")).hexdigest() if token else None
    )
    with application.config_lock:
        if token_key != application.anlas_balance_token_key:
            application.anlas_balance_cache = None
            application.anlas_balance_token_key = token_key
    fresh = operations.fetch_balance(token) if requested else None
    with application.config_lock:
        if fresh and token_key == application.anlas_balance_token_key:
            application.anlas_balance_cache = fresh
        known = (
            application.anlas_balance_cache
            if token_key == application.anlas_balance_token_key
            else None
        )
    return fresh, known


def _reference_count(config: dict, data: dict) -> int:
    if "char_refs" in data:
        return max(0, int(data.get("char_refs")))
    return sum(
        1 for reference in config.get("char_refs", [])
        if reference.get("enabled")
    )


def _new_vibe_count(config: dict, operations: Any) -> int:
    count = 0
    for vibe in config.get("vibes", []):
        if not vibe.get("enabled"):
            continue
        _, encoded_path = operations.vibe_paths(vibe.get("id", ""))
        information = float(vibe.get("info_extracted", 0.7))
        encoded_information = float(vibe.get("encoded_ie", -1) or -1)
        if (
            not encoded_path.exists()
            or abs(encoded_information - information) > 1e-9
        ):
            count += 1
    return count


def _batch_reason(
    config: dict,
    known_balance: dict | None,
    *,
    opus: bool,
    references: int,
    new_vibes: int,
    total: int,
    eligible_all: bool,
) -> str:
    if total == 0:
        return "Opus 무료 (모든 씬이 1024² 이하 · 28스텝 이하)"
    if not eligible_all:
        return (
            f"{config.get('steps')}스텝 / 일부 씬 해상도가 무료 조건"
            f"(1024² 이하·28스텝 이하)을 넘습니다"
        )
    parts = []
    if known_balance is None:
        parts.append("무료 크기·스텝 범위 · Opus 등급 미확인")
    elif not opus:
        parts.append("무료 크기·스텝 범위 · 비Opus 등급")
    else:
        parts.append("Opus 무료 생성")
    if references:
        parts.append(
            f"캐릭터 레퍼런스 {references}개 장당 {5 * references} Anlas"
        )
    if new_vibes:
        parts.append(f"새 바이브 {new_vibes}개 인코딩 {2 * new_vibes} Anlas")
    return " + ".join(parts)


def _batch_estimate(
    config: dict,
    operations: Any,
    known_balance: dict | None,
    *,
    opus: bool,
    references: int,
    new_vibes: int,
) -> dict:
    asset_config = operations.load_asset_config(config)
    pending = operations.compute_pending(config, asset_config, {}, set())
    total = 0
    eligible_all = True
    generation_free_all = True
    for _, _, number, _ in pending:
        scene = asset_config["scenes"].get(str(number)) or {}
        estimate = operations.estimate_anlas(
            config,
            1,
            scene.get("width"),
            scene.get("height"),
            opus=opus,
            char_refs=references,
        )
        total += estimate["total"]
        eligible_all = eligible_all and estimate["free_eligible"]
        generation_free_all = (
            generation_free_all and estimate["generation_free"]
        )
    total += 2 * new_vibes
    return {
        "per_image": None,
        "total": total,
        "count": len(pending),
        "free": total == 0,
        "free_eligible": eligible_all,
        "generation_free": generation_free_all,
        "batch": True,
        "width": None,
        "height": None,
        "steps": int(config.get("steps", 28)),
        "vibe_encode": 2 * new_vibes,
        "char_refs": references,
        "why": _batch_reason(
            config,
            known_balance,
            opus=opus,
            references=references,
            new_vibes=new_vibes,
            total=total,
            eligible_all=eligible_all,
        ),
    }


def anlas_response(
    application: Any,
    operations: Any,
    data: dict,
) -> dict:
    """화면의 단일·배치 조건을 실제 pending 작업과 같은 비용 규칙으로 계산한다."""
    fresh_balance, known_balance = _balance(
        application, operations, bool(data.get("balance"))
    )
    opus = bool(known_balance and known_balance.get("opus"))
    config = application.cfg
    references = _reference_count(config, data)
    new_vibes = _new_vibe_count(config, operations)
    if data.get("batch"):
        estimate = _batch_estimate(
            config,
            operations,
            known_balance,
            opus=opus,
            references=references,
            new_vibes=new_vibes,
        )
    else:
        estimate = operations.estimate_anlas(
            config,
            int(data.get("count") or 1),
            width=data.get("width"),
            height=data.get("height"),
            opus=opus,
            char_refs=references,
            mode=(data.get("mode") or "t2i"),
            strength=float(data.get("strength") or 1.0),
        )
        estimate["total"] += 2 * new_vibes
        estimate["vibe_encode"] = 2 * new_vibes
    estimate["subscription_known"] = known_balance is not None
    estimate["opus"] = (
        bool(known_balance.get("opus"))
        if known_balance is not None
        else None
    )
    return {
        "ok": True,
        "est": estimate,
        "balance": fresh_balance if data.get("balance") else None,
    }


def token_response(application: Any, operations: Any, data: dict) -> dict:
    """저장값을 바꾸지 않고 최종 전송 직전 텍스트와 같은 토큰 수를 돌려준다."""
    if data.get("finalize"):
        final = operations.finalize_tokens(
            data.get("base", ""),
            data.get("negative", ""),
            data.get("chars") or [],
            data.get("char_negatives") or [],
            application.cfg,
        )
    else:
        final = {
            "base": data.get("base", ""),
            "negative": data.get("negative", ""),
            "chars": data.get("chars") or [],
            "char_negatives": data.get("char_negatives") or [],
        }
    base = operations.token_count(final["base"])
    chars = [operations.token_count(text) for text in final["chars"]]
    negative = operations.token_count(final["negative"])
    char_negatives = [
        operations.token_count(text) for text in final["char_negatives"]
    ]
    return {
        "ok": True,
        "exact": operations.tokens_exact(),
        "base": base,
        "negative": negative,
        "chars": chars,
        "char_negatives": char_negatives,
        "shared": base + sum(chars),
        "shared_negative": negative + sum(char_negatives),
        "limit": 512,
        "finalized": bool(data.get("finalize")),
    }


def finalized_token_texts(
    base: str,
    negative: str,
    characters: list,
    character_negatives: list,
    config: dict,
    *,
    strip_comments: Any,
    load_state: Any,
    resolve_fragments: Any,
    normalize_prompt: Any,
    merge_quality_suffix: Any,
    merge_uc_preset: Any,
) -> dict:
    """미리보기에서 fragment 상태를 소비하지 않고 실제 전송 문자열을 조립한다."""
    characters = list(characters or [])
    character_negatives = list(character_negatives or [])
    count = max(len(characters), len(character_negatives))
    characters += [""] * (count - len(characters))
    character_negatives += [""] * (
        count - len(character_negatives)
    )
    pairs = [
        [characters[index], character_negatives[index]]
        for index in range(count)
    ]
    fixed = [
        strip_comments(value)
        for value in (base, negative, "", "", "", "")
    ]
    flat = [
        strip_comments(value)
        for pair in pairs
        for value in pair
    ]
    if config.get("use_fragments", True):
        counters = config.get("_frag_counters")
        if counters is None:
            try:
                counters = load_state().get("frag_seq", {})
            except Exception:
                counters = {}
        resolved, _ = resolve_fragments(
            fixed + flat,
            counters=dict(counters or {}),
            rng=random.Random(0),
        )
        fixed = list(resolved[:6])
        flat = list(resolved[6:])
    fixed = [normalize_prompt(value) for value in fixed]
    flat = [normalize_prompt(value) for value in flat]
    base, negative = fixed[0], fixed[1]
    model = config.get("model") or "nai-diffusion-4-5-full"
    if config.get("quality_toggle"):
        base = merge_quality_suffix(base, model)
    negative = merge_uc_preset(
        negative,
        model,
        config.get("uc_preset"),
    )
    return {
        "base": base,
        "negative": negative,
        "chars": [flat[index * 2] for index in range(count)],
        "char_negatives": [
            flat[index * 2 + 1]
            for index in range(count)
        ],
    }


def runtime_generation_params(
    config: dict,
    token: str,
    *,
    include_refs: bool = True,
    prepare_vibes: Any,
    prepare_char_refs: Any,
    info: Any,
    warn: Any,
) -> dict:
    """한 NAI 호출에만 쓸 Vibe·Character Reference 파생값을 만든다."""
    params = dict(config or {})
    params.pop("_vibes", None)
    params.pop("_char_refs", None)
    if not include_refs:
        return params
    active_vibes = [
        item
        for item in (config.get("vibes") or [])
        if isinstance(item, dict) and item.get("enabled")
    ]
    active_char_refs = [
        item
        for item in (config.get("char_refs") or [])
        if isinstance(item, dict) and item.get("enabled")
    ]
    if active_vibes and active_char_refs:
        raise ValueError(
            "NAI에서는 바이브와 캐릭터 레퍼런스를 동시에 사용할 수 없습니다. "
            "둘 중 하나를 꺼주세요."
        )
    try:
        encoded, strengths, ies, newly = prepare_vibes(config, token)
        images, types, ref_strengths, fidelities = prepare_char_refs(config)
        params["_vibes"] = {
            "encoded": encoded,
            "strengths": strengths,
            "ies": ies,
        }
        params["_char_refs"] = {
            "images": images,
            "types": types,
            "strengths": ref_strengths,
            "fidelities": fidelities,
        }
        if newly:
            info(f"바이브 {newly}개를 새로 인코딩했습니다.")
    except Exception as error:
        if any(
            item.get("enabled") and item.get("_required")
            for item in (config.get("char_refs") or [])
            if isinstance(item, dict)
        ):
            raise
        warn(f"레퍼런스 준비 실패 — 레퍼런스 없이 계속합니다: {error}")
        params["_vibes"] = {}
        params["_char_refs"] = {}
    return params


__all__ = [
    "anlas_response",
    "finalized_token_texts",
    "runtime_generation_params",
    "token_response",
]
