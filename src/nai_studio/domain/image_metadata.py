# -*- coding: utf-8 -*-
"""PNG·WebP·Stealth 메타데이터를 NAI 생성 정보로 복원하는 순수 경계.

이미지 바이트와 메타데이터만 다루며 사용자 파일·설정·HTTP에는 접근하지 않는다.
"""
from __future__ import annotations

import gzip
import json
import re
import struct
import zlib

from src.nai_studio.domain.positioning import normalize_position_mode

# ══════════════════════════════════════════════════════════════════════
#  NAI 메타데이터 추출 — novelai.net/inspect 가 하는 일을 로컬에서
#  PNG tEXt/zTXt/iTXt + 스텔스(알파 채널 LSB) + WebP EXIF.
#  아카 이미지는 업로드 과정에서 텍스트 청크가 지워지는 경우가 많아
#  (표본 150장 중 111장) 스텔스 판독이 필수다. Pillow 없이도 동작한다.
# ══════════════════════════════════════════════════════════════════════
# `1.2::artist:foo74::` 처럼 숫자로 끝나는 태그가 `::`에 붙으면 NAI가 가중치로 오해한다.
# 닫는 `::` 앞에 공백을 넣어 원래 의도대로 읽히게 정규화한다.
_W_GROUP = re.compile(r"([+-]?\d+(?:\.\d+)?)::([\s\S]*?)::")
_ARTIST_CLOSER = re.compile(r"(artist\s*:[^,\n]*?\d)\s*::", re.I)

# `#` 로 **시작하는 줄**은 메모다 — 전송·미리보기·토큰 계산에서 뺀다
# (NAIS3-Custom 의 프롬프트 주석 참고). 줄 중간의 # 는 건드리지 않는다.
_COMMENT_LINE = re.compile(r"^[ \t]*#[^\n]*\n?", re.M)


def strip_comment_lines(text):
    t = str(text or "")
    return _COMMENT_LINE.sub("", t) if "#" in t else t


def normalize_prompt(prompt):
    prompt = strip_comment_lines(prompt)   # 주석 줄은 애초에 프롬프트가 아니다
    def fix(m):
        body = m.group(2).rstrip()
        if body[-1:].isdigit():
            body += " "
        return f"{m.group(1)}::{body}::"
    return _ARTIST_CLOSER.sub(lambda m: f"{m.group(1)} ::", _W_GROUP.sub(fix, str(prompt or "")))

GENERATION_KEYS = {"seed", "sampler", "steps", "scale", "noise_schedule",
                   "model", "width", "height"}
TEXT_KEYS = {"comment", "description", "software", "source", "parameters", "prompt", "uc"}


# ────────────────────────── PNG: 텍스트 청크 ──────────────────────────
def png_text_chunks(data):
    """tEXt / zTXt / iTXt 청크를 {키: 값} 으로."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return {}
    pos, out = 8, {}
    while pos + 12 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        try:
            if kind == b"tEXt":
                k, v = payload.split(b"\0", 1)
                out[k.decode("latin1")] = v.decode("utf-8", "replace")
            elif kind == b"zTXt":
                k, rest = payload.split(b"\0", 1)
                out[k.decode("latin1")] = zlib.decompress(rest[1:]).decode("utf-8", "replace")
            elif kind == b"iTXt":
                k, rest = payload.split(b"\0", 1)
                compressed = rest[0]
                rest = rest[2:]
                _, rest = rest.split(b"\0", 1)     # language tag
                _, v = rest.split(b"\0", 1)        # translated keyword
                out[k.decode("latin1")] = (zlib.decompress(v) if compressed else v).decode("utf-8", "replace")
        except (ValueError, IndexError, zlib.error):
            pass
        if kind == b"IEND":
            break
    return out


# ─────────────────── PNG: 알파 채널만 뽑는 최소 디코더 ───────────────────
def _alpha_via_pillow(data):
    """Pillow가 있으면 알파 추출을 맡긴다 (순수 파이썬 디코더보다 10배 이상 빠름)."""
    try:
        import io
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.mode != "RGBA":
                return None
            return im.size[0], im.size[1], im.getchannel("A").tobytes()
    except Exception:
        return None


def _png_alpha_channel(data):
    """비인터레이스 RGBA/GA 8·16비트 PNG에서 (width, height, alpha bytes) 반환.
    Pillow 없이 스텔스 정보를 읽기 위한 최소 구현."""
    fast = _alpha_via_pillow(data)
    if fast:
        return fast
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    pos, idat, ihdr = 8, [], None
    while pos + 12 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", payload)
        elif kind == b"IDAT":
            idat.append(payload)
        elif kind == b"IEND":
            break
    if not ihdr or not idat:
        return None
    width, height, depth, color, comp, filt, interlace = ihdr
    # 알파가 있는 형식만 (4=회색+알파, 6=트루컬러+알파)
    if color not in (4, 6) or depth not in (8, 16) or comp or filt or interlace:
        return None
    channels = 2 if color == 4 else 4
    bpp = channels * depth // 8               # 픽셀당 바이트
    stride = width * bpp
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error:
        return None
    if len(raw) < height * (stride + 1):
        return None

    prev = bytearray(stride)
    alpha = bytearray(width * height)
    step = depth // 8
    off = 0
    for y in range(height):
        ftype = raw[off]
        line = bytearray(raw[off + 1:off + 1 + stride])
        off += 1 + stride
        if ftype == 1:                                  # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:                                # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:                                # Average
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:                                # Paeth
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif ftype != 0:
            return None
        # 알파는 픽셀의 마지막 채널 — 16비트면 상위 바이트만 쓰면 되지만
        # 스텔스는 8비트 저장이므로 최하위 바이트를 취한다.
        base = (channels - 1) * step + (step - 1)
        row = y * width
        for x in range(width):
            alpha[row + x] = line[x * bpp + base]
        prev = line
    return width, height, bytes(alpha)


def read_stealth_info(data, alpha=None):
    """알파 채널 LSB에 숨겨진 stealth_pnginfo / stealth_pngcomp 페이로드."""
    if alpha is None:
        alpha = _png_alpha_channel(data)
    if not alpha:
        return None
    width, height, buf = alpha

    def bit(i):
        x, y = divmod(i, height)
        if x >= width:
            raise ValueError("stealth payload exceeds image bounds")
        return str(buf[y * width + x] & 1)

    try:
        sig_bits = "".join(bit(i) for i in range(120))
        sig = bytes(int(sig_bits[i:i + 8], 2) for i in range(0, 120, 8)).decode("utf-8", "ignore")
        if sig not in {"stealth_pngcomp", "stealth_pnginfo"}:
            return None
        n = int("".join(bit(i) for i in range(120, 152)), 2)
        if n <= 0 or n % 8 or 152 + n > width * height:
            return None
        bits = "".join(bit(i) for i in range(152, 152 + n))
        payload = bytes(int(bits[i:i + 8], 2) for i in range(0, n, 8))
        if sig == "stealth_pngcomp":
            payload = gzip.decompress(payload)
        return payload.decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError, zlib.error):
        return None


# ───────────────────────── 값 병합 / 파싱 ─────────────────────────
def _merge(values, raw, allow_plain_prompt=True):
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            by = {str(k).casefold(): v for k, v in parsed.items()}
            comment = by.get("comment")
            if isinstance(comment, str):
                try:
                    nested = json.loads(comment)
                    if isinstance(nested, dict):
                        parsed = nested
                except json.JSONDecodeError:
                    pass
            desc = str(by.get("description") or "").strip()
            src = str(by.get("source") or "").strip()
            soft = str(by.get("software") or "").strip()
            if desc:
                parsed.setdefault("prompt", desc)
            if src:
                parsed.setdefault("source", src)
                if src.casefold().startswith("novelai diffusion"):
                    parsed.setdefault("model", src)
            if soft:
                parsed.setdefault("software", soft)
            values.update(parsed)
            return
    except (json.JSONDecodeError, TypeError):
        pass
    text = str(raw).split("Negative prompt:", 1)[0].strip()
    if allow_plain_prompt and text:
        values.setdefault("prompt", text)


def _webp_values(data):
    """WebP는 Pillow가 있어야 EXIF를 읽을 수 있다. 없으면 빈 dict."""
    try:
        import io
        from PIL import Image
    except ImportError:
        return {}
    values = {}
    try:
        with Image.open(io.BytesIO(data)) as im:
            if str(im.format or "").upper() != "WEBP":
                return {}
            by = {str(k).casefold(): v for k, v in im.info.items()}
            for key in ("parameters", "comment", "description", "prompt", "uc"):
                raw = by.get(key)
                if raw in (None, b"", ""):
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", "ignore")
                if key == "uc":
                    values.setdefault("uc", str(raw))
                else:
                    _merge(values, raw)
            exif = im.getexif() if hasattr(im, "getexif") else None
            if not exif:
                return values
            uc = exif.get(37510)
            if uc in (None, b"", "") and hasattr(exif, "get_ifd"):
                try:
                    uc = exif.get_ifd(34665).get(37510)
                except (KeyError, TypeError, ValueError):
                    uc = None
            if uc not in (None, b"", ""):
                if isinstance(uc, bytes):
                    if uc.startswith(b"UNICODE\x00"):
                        for enc in ("utf-16-be", "utf-16-le", "utf-16"):
                            try:
                                uc = uc[8:].decode(enc); break
                            except UnicodeDecodeError:
                                continue
                        else:
                            uc = uc[8:].decode("utf-8", "ignore")
                    elif uc.startswith(b"ASCII\x00\x00\x00"):
                        uc = uc[8:].decode("utf-8", "ignore")
                    else:
                        uc = uc.decode("utf-8", "ignore")
                uc = str(uc).replace("\x00", "").strip()
                if uc:
                    _merge(values, uc)
            for tag, key in ((270, None), (305, "software")):
                v = exif.get(tag)
                if v in (None, b"", ""):
                    continue
                if isinstance(v, bytes):
                    v = v.decode("utf-8", "ignore")
                if key:
                    values.setdefault(key, str(v).strip())
                else:
                    _merge(values, v)
    except Exception:
        return {}
    return values


def _is_nai(values):
    if not isinstance(values, dict):
        return False
    if isinstance(values.get("v4_prompt"), dict):
        return True
    soft = str(values.get("software") or "").casefold()
    src = str(values.get("source") or "").casefold()
    if values.get("prompt") and (soft.startswith("novelai") or src.startswith("novelai diffusion")):
        return True
    return bool(values.get("prompt")) and len(GENERATION_KEYS & set(values)) >= 2


def _prompt_parts(values):
    v4 = values.get("v4_prompt") if isinstance(values.get("v4_prompt"), dict) else {}
    cap = v4.get("caption") if isinstance(v4.get("caption"), dict) else {}
    base = normalize_prompt(cap.get("base_caption") or values.get("prompt")
                            or values.get("prompts") or "")
    chars = []
    for e in (cap.get("char_captions") or []) if isinstance(cap.get("char_captions"), list) else []:
        if isinstance(e, dict) and e.get("char_caption"):
            chars.append({"prompt": normalize_prompt(e["char_caption"]),
                          "negative": "",
                          "centers": e.get("centers") if isinstance(e.get("centers"), list) else []})
    v4n = values.get("v4_negative_prompt") if isinstance(values.get("v4_negative_prompt"), dict) else {}
    ncap = v4n.get("caption") if isinstance(v4n.get("caption"), dict) else {}
    neg_chars = (ncap.get("char_captions") or []) if isinstance(
        ncap.get("char_captions"), list) else []
    # 캐릭터 1·2는 세부 태그로 다시 쪼개지 않고, 메타데이터에 든 각 캐릭터의
    # 전체 프롬프트와 전용 네거티브를 같은 순서로 그대로 묶어 둔다.
    for i, e in enumerate(neg_chars):
        if not isinstance(e, dict):
            continue
        while len(chars) <= i:
            chars.append({"prompt": "", "negative": "", "centers": []})
        chars[i]["negative"] = normalize_prompt(e.get("char_caption") or "")
    neg = normalize_prompt(ncap.get("base_caption") or values.get("uc")
                           or values.get("negative_prompt")
                           or values.get("undesired_content") or "")
    return str(base), str(neg), chars


PARAM_KEYS = ("seed", "sampler", "steps", "scale", "cfg_rescale", "noise_schedule",
              "width", "height", "uncond_scale", "dynamic_thresholding",
              "controlnet_strength", "deliberate_euler_ancestral_bug",
              "prefer_brownian", "skip_cfg_above_sigma", "sm", "sm_dyn")


def extract_nai_metadata(data, content_type=""):
    out = {"metadata_status": "no_metadata", "base": "", "negative": "",
           "characters": [], "params": {}, "raw": {}}
    if not isinstance(data, (bytes, bytearray)) or len(data) < 12:
        return out
    data = bytes(data)
    ct = (content_type or "").lower()
    is_png = data.startswith(b"\x89PNG") or "png" in ct
    is_webp = (data[:4] == b"RIFF" and data[8:12] == b"WEBP") or "webp" in ct
    if not (is_png or is_webp):
        return out

    values = _webp_values(data) if is_webp else {}
    if is_png:
        for key, raw in png_text_chunks(data).items():
            k = key.lower()
            if k not in TEXT_KEYS:
                continue
            if k == "uc":
                values["uc"] = raw
            elif k == "source":
                s = str(raw or "").strip()
                if s:
                    values.setdefault("source", s)
                    if s.casefold().startswith("novelai diffusion"):
                        values.setdefault("model", s)
            else:
                _merge(values, raw, allow_plain_prompt=k not in {"software", "source"})
        if not _is_nai(values):                       # 텍스트 청크가 지워졌으면 스텔스
            stealth = read_stealth_info(data)
            if stealth:
                _merge(values, stealth)

    if not _is_nai(values):
        return out
    base, neg, chars = _prompt_parts(values)
    if not base and not neg:
        return out

    params = {k: values[k] for k in PARAM_KEYS if values.get(k) is not None}
    if "seed" in params:
        params["seed"] = str(params["seed"])
    if "skip_cfg_above_sigma" in values:
        params["variety_plus"] = bool(values.get("skip_cfg_above_sigma"))
    if values.get("ucPreset") is not None:
        try:
            params["uc_preset"] = int(values["ucPreset"])
        except (TypeError, ValueError):
            pass
    if values.get("qualityToggle") is not None:
        params["quality_toggle"] = bool(values["qualityToggle"])
    v4 = values.get("v4_prompt") if isinstance(values.get("v4_prompt"), dict) else {}
    if v4.get("use_coords") is not None:
        params["use_coords"] = bool(v4.get("use_coords"))
        # NAI 메타에는 위치판/연속 좌표 UI 구분이 없다. 좌표를 사용한 파일은
        # 값을 잃지 않는 coordinate로 복원하고, 끈 파일은 AI 자동으로 복원한다.
        params["position_mode"] = normalize_position_mode(
            "", params["use_coords"])
    model = values.get("model") or values.get("source") or ""
    if model:
        params["model"] = str(model)
    out.update({"metadata_status": "ok", "base": base, "negative": neg,
                "characters": chars, "params": params, "raw": values})
    return out

__all__ = [
    "GENERATION_KEYS", "PARAM_KEYS", "TEXT_KEYS", "_prompt_parts",
    "extract_nai_metadata", "normalize_prompt", "png_text_chunks",
    "read_stealth_info", "strip_comment_lines",
]
