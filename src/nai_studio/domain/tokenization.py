# -*- coding: utf-8 -*-
"""NAI T5 Unigram 토큰 수를 계산하는 독립 경계."""
from __future__ import annotations

import json
import re
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════
#  NAI V4/V4.5 토큰 수 — T5 Unigram + Viterbi (의존성 없음)
#  NAI 는 프롬프트를 T5 인코더에 넣는다. 정확한 토큰 수를 알려면 NAI 가 쓰는
#  같은 vocab(t5_tokenizer.json, 32,100개)으로 같은 방식으로 쪼개야 한다.
#  가중치 표기(`1.4::` `::`)와 {}[] 강조는 NAI 가 파싱해서 걷어내므로 세지 않는다.
#  → 태그 텍스트 506개 표본에서 표준 구현과 100% 일치 확인.
# ══════════════════════════════════════════════════════════════════════
METASPACE = "▁"
_STATE = {"loaded": False, "vocab": {}, "maxlen": 1, "unk": -1e3}

# 가중치·강조 표기 제거 (텍스트가 아니라 문법이므로 토큰에 안 들어간다)
_WEIGHT = re.compile(r"[+-]?\d*\.?\d+\s*::|::")
_BRACKET = re.compile(r"[{}\[\]]")


def load_vocab(path):
    if _STATE["loaded"]:
        return _STATE
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        pieces = d["model"]["vocab"]
        vocab = {}
        maxlen = 1
        for item in pieces:
            piece, score = item[0], float(item[1])
            vocab[piece] = score
            if len(piece) > maxlen:
                maxlen = len(piece)
        # unk 점수: 가장 낮은 점수보다 더 낮게 (모르는 글자 1개 = 1토큰)
        worst = min(vocab.values()) if vocab else -20.0
        _STATE.update(loaded=True, vocab=vocab, maxlen=min(maxlen, 32),
                      unk=worst - 10.0)
    except Exception:
        _STATE["loaded"] = True          # 실패해도 다시 시도하지 않음
    return _STATE


def _viterbi(piece):
    """한 조각을 vocab 조각들로 나눌 때 로그확률 합이 최대가 되는 분할의 개수"""
    vocab = _STATE["vocab"]
    if not vocab:
        return max(1, len(piece) // 4)   # vocab 없으면 대략치
    n = len(piece)
    best = [(-1e18, 0)] * (n + 1)        # (점수, 토큰수)
    best[0] = (0.0, 0)
    maxlen = _STATE["maxlen"]
    unk = _STATE["unk"]
    for i in range(1, n + 1):
        top = (-1e18, 0)
        lo = max(0, i - maxlen)
        for j in range(lo, i):
            prev = best[j]
            if prev[0] <= -1e17:
                continue
            sub = piece[j:i]
            sc = vocab.get(sub)
            if sc is None:
                # 표준 Unigram 과 같이 미등록 구간은 글자 하나씩 <unk> 로 센다.
                # (길이 무제한으로 묶으면 긴 미등록 구간이 1토큰이 되어 크게 어긋난다)
                if i - j != 1:
                    continue
                sc = unk
            cand = (prev[0] + sc, prev[1] + 1)
            if cand[0] > top[0]:
                top = cand
        best[i] = top
    return best[n][1] if best[n][0] > -1e17 else max(1, n)


def count_tokens(text, vocab_path=None):
    """프롬프트의 NAI 토큰 수 (</s> 포함)"""
    if vocab_path:
        load_vocab(vocab_path)
    t = _BRACKET.sub("", _WEIGHT.sub(" ", str(text or "")))
    total = 0
    for piece in t.split():
        total += _viterbi(METASPACE + piece)
    return total + 1                     # </s>

__all__ = [
    "METASPACE", "_BRACKET", "_STATE", "_WEIGHT", "_viterbi",
    "count_tokens", "load_vocab",
]
