# -*- coding: utf-8 -*-
"""설계도·설정 저장·비용·토큰 계산 POST 라우트."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimePostOperations:
    blueprint_project: Any
    save_config: Any
    fetch_balance: Any
    vibe_paths: Any
    load_asset_config: Any
    compute_pending: Any
    estimate_anlas: Any
    finalize_tokens: Any
    token_count: Any
    tokens_exact: Any


def _json_body(body: bytes) -> dict:
    value = json.loads(body or b"{}")
    return value if isinstance(value, dict) else {}


def _balance(
    application: Any,
    operations: RuntimePostOperations,
    requested: bool,
) -> tuple[dict | None, dict | None]:
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
    return sum(1 for reference in config.get("char_refs", []) if reference.get("enabled"))


def _new_vibe_count(config: dict, operations: RuntimePostOperations) -> int:
    count = 0
    for vibe in config.get("vibes", []):
        if not vibe.get("enabled"):
            continue
        _, encoded_path = operations.vibe_paths(vibe.get("id", ""))
        information = float(vibe.get("info_extracted", 0.7))
        encoded_information = float(vibe.get("encoded_ie", -1) or -1)
        if not encoded_path.exists() or abs(encoded_information - information) > 1e-9:
            count += 1
    return count


def _batch_reason(
    config: dict,
    known_balance: dict | None,
    facts: dict,
) -> str:
    opus = facts["opus"]
    references = facts["references"]
    new_vibes = facts["new_vibes"]
    total = facts["total"]
    eligible_all = facts["eligible_all"]
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
        parts.append(f"캐릭터 레퍼런스 {references}개 장당 {5 * references} Anlas")
    if new_vibes:
        parts.append(f"새 바이브 {new_vibes}개 인코딩 {2 * new_vibes} Anlas")
    return " + ".join(parts)


def _batch_estimate(
    config: dict,
    operations: RuntimePostOperations,
    known_balance: dict | None,
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
            config, 1, scene.get("width"), scene.get("height"),
            opus=opus, char_refs=references,
        )
        total += estimate["total"]
        eligible_all = eligible_all and estimate["free_eligible"]
        generation_free_all = generation_free_all and estimate["generation_free"]
    total += 2 * new_vibes
    return {
        "per_image": None, "total": total, "count": len(pending),
        "free": total == 0, "free_eligible": eligible_all,
        "generation_free": generation_free_all, "batch": True,
        "width": None, "height": None, "steps": int(config.get("steps", 28)),
        "vibe_encode": 2 * new_vibes, "char_refs": references,
        "why": _batch_reason(
            config,
            known_balance,
            {
                "opus": opus, "references": references, "new_vibes": new_vibes,
                "total": total, "eligible_all": eligible_all,
            },
        ),
    }


def _anlas(
    application: Any,
    operations: RuntimePostOperations,
    data: dict,
) -> dict:
    fresh_balance, known_balance = _balance(
        application, operations, bool(data.get("balance"))
    )
    opus = bool(known_balance and known_balance.get("opus"))
    config = application.cfg
    references = _reference_count(config, data)
    new_vibes = _new_vibe_count(config, operations)
    if data.get("batch"):
        estimate = _batch_estimate(
            config, operations, known_balance, opus, references, new_vibes
        )
    else:
        estimate = operations.estimate_anlas(
            config, int(data.get("count") or 1),
            width=data.get("width"), height=data.get("height"),
            opus=opus, char_refs=references, mode=(data.get("mode") or "t2i"),
            strength=float(data.get("strength") or 1.0),
        )
        estimate["total"] += 2 * new_vibes
        estimate["vibe_encode"] = 2 * new_vibes
    estimate["subscription_known"] = known_balance is not None
    estimate["opus"] = (
        bool(known_balance.get("opus")) if known_balance is not None else None
    )
    return {
        "ok": True, "est": estimate,
        "balance": fresh_balance if data.get("balance") else None,
    }


def _tokens(
    application: Any,
    operations: RuntimePostOperations,
    data: dict,
) -> dict:
    if data.get("finalize"):
        final = operations.finalize_tokens(
            data.get("base", ""), data.get("negative", ""),
            data.get("chars") or [], data.get("char_negatives") or [],
            application.cfg,
        )
    else:
        final = {
            "base": data.get("base", ""), "negative": data.get("negative", ""),
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
        "ok": True, "exact": operations.tokens_exact(), "base": base,
        "negative": negative, "chars": chars, "char_negatives": char_negatives,
        "shared": base + sum(chars),
        "shared_negative": negative + sum(char_negatives), "limit": 512,
        "finalized": bool(data.get("finalize")),
    }


def handle_runtime_post(
    request: Any,
    application: Any,
    operations: RuntimePostOperations,
    body: bytes,
) -> bool:
    try:
        if request.path.startswith("/api/blueprint_project"):
            result = operations.blueprint_project(body)
        elif request.path.startswith("/api/save"):
            result = operations.save_config(body)
        elif request.path.startswith("/api/anlas"):
            result = _anlas(application, operations, _json_body(body))
        elif request.path.startswith("/api/tokens"):
            result = _tokens(application, operations, _json_body(body))
        else:
            return False
        request._json(result)
    except Exception as exc:
        request._json({"ok": False, "error": str(exc)})
    return True


__all__ = ["RuntimePostOperations", "handle_runtime_post"]
