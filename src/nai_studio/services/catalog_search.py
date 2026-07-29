# -*- coding: utf-8 -*-
"""공개 booru 검색과 NAI 태그 표기·검증 경계."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


BOORUS = {
    "danbooru": {
        "name": "단부루",
        "url": "https://danbooru.donmai.us/posts.json",
        "page": "https://danbooru.donmai.us/posts",
        "auth": "basic",
    },
    "gelbooru": {
        "name": "겔부루",
        "note": " (API 키 필요)",
        "auth": "gel",
        "url": (
            "https://gelbooru.com/index.php?"
            "page=dapi&s=post&q=index&json=1"
        ),
        "page": (
            "https://gelbooru.com/index.php?"
            "page=post&s=list"
        ),
    },
    "e621": {
        "name": "e621",
        "note": " (지역 차단)",
        "auth": "basic",
        "url": "https://e621.net/posts.json",
        "page": "https://e621.net/posts",
    },
}

DANBOORU_MIRRORS = [
    "danbooru.donmai.us",
    "hijiribe.donmai.us",
    "sonohara.donmai.us",
]
DANBOORU_SFW_MIRROR = "safebooru.donmai.us"

BOORU_AUTH_HELP = {
    "danbooru": (
        "danbooru.donmai.us → My Account → API Key. "
        "골드 이상이면 태그 제한이 2개에서 6개로 풀린다."
    ),
    "gelbooru": (
        "gelbooru.com → My Account → Options 맨 아래 API Access "
        "Credentials (user_id 와 api_key 가 함께 나온다)."
    ),
    "e621": (
        "e621.net → Account → Manage API Access. "
        "지역 차단이면 키가 있어도 451 이다."
    ),
}

NAI_RENAMED_TAGS = {
    "v": "peace sign",
    "double_v": "double peace",
    "|_|": "bar eyes",
    r"\||/": r"open \m/",
    ":|": "neutral face",
    ";|": "neutral face",
    "<|>_<|>": "neco-arc eyes",
    "eyepatch_bikini": "square bikini",
    "tachi-e": "character image",
}


@dataclass(frozen=True)
class CatalogSearchPaths:
    """credential fallback이 읽는 현재 프로필 설정 위치."""

    settings_file: Path


@dataclass
class CatalogSearchState:
    """호출 간 공유해야 하는 credential·throttle·태그 판정 캐시."""

    booru_keys: dict[str, Any]
    booru_last: list[float]
    booru_lock: Any
    tag_cache: dict[str, tuple[int, bool] | None]


@dataclass(frozen=True)
class CatalogSearchOperations:
    """네트워크·시간·기록 의존성을 호출자가 현재 전역에서 주입한다."""

    request_get: Callable[..., Any]
    request_errors: tuple[type[BaseException], ...]
    clock: Callable[[], float]
    sleep: Callable[[float], Any]
    log_info: Callable[..., Any]
    log_warning: Callable[..., Any]
    user_agent: str


def booru_creds(
    paths: CatalogSearchPaths,
    state: CatalogSearchState,
    site: str,
) -> tuple[str, str]:
    """메모리 설정을 우선하고 없을 때만 현재 설정 파일의 계정을 읽는다."""
    keys = state.booru_keys.get(site)
    if keys is None:
        try:
            with open(paths.settings_file, encoding="utf-8") as stream:
                keys = (
                    (json.load(stream).get("booru_keys") or {}).get(site)
                    or {}
                )
        except (OSError, ValueError):
            keys = {}
    return (
        str(keys.get("user") or "").strip(),
        str(keys.get("key") or "").strip(),
    )


def booru_throttle(
    state: CatalogSearchState,
    operations: CatalogSearchOperations,
    gap: float = 1.0,
) -> None:
    """공유 잠금과 마지막 호출 시각으로 검색 요청의 최소 간격을 지킨다."""
    with state.booru_lock:
        wait = gap - (operations.clock() - state.booru_last[0])
        if wait > 0:
            operations.sleep(wait)
        state.booru_last[0] = operations.clock()


def _normalize_booru_tags(
    site: str,
    tags: str,
    credentials: Callable[[str], tuple[str, str]],
) -> tuple[str, str]:
    parts = [
        re.sub(r"^artists?:", "", tag, flags=re.I).replace(" ", "_")
        for tag in (tags or "").split()
        if tag
    ]
    note = ""
    if site == "danbooru" and len(parts) > 2:
        cap = 6 if all(credentials("danbooru")) else 2
        if len(parts) > cap:
            note = (
                f"단부루는 태그 {cap}개까지만 검색됩니다 — "
                f"앞 {cap}개만 씁니다: {' '.join(parts[:cap])}"
                + (
                    ""
                    if cap > 2
                    else (
                        " (관리 → API 에 단부루 계정을 넣으면 "
                        "6개까지)"
                    )
                )
            )
            parts = parts[:cap]
    return " ".join(parts)[:200], note


def _booru_request_options(
    config: dict[str, Any],
    site: str,
    tags: str,
    page: int,
    limit: int,
    credentials: Callable[[str], tuple[str, str]],
    user_agent: str,
) -> tuple[dict, dict, tuple[str, str] | None, dict | None]:
    headers = {"User-Agent": user_agent}
    params = (
        {"tags": tags, "limit": limit, "pid": max(0, page - 1)}
        if site == "gelbooru"
        else {"tags": tags, "limit": limit, "page": page}
    )
    auth = None
    user, key = credentials(site)
    if user and key:
        if config.get("auth") == "gel":
            params["user_id"], params["api_key"] = user, key
        else:
            auth = (user, key)
    elif site == "gelbooru":
        return headers, params, auth, {
            "ok": False,
            "error": (
                "겔부루는 API 키가 있어야 검색됩니다. "
                "관리 → API 의 '부루 계정' 에 user_id 와 api_key 를 "
                "넣어 주세요."
            ),
        }
    return headers, params, auth, None


def _booru_urls(config: dict[str, Any], site: str) -> list[str]:
    if site != "danbooru":
        return [config["url"]]
    return [
        config["url"].replace(DANBOORU_MIRRORS[0], host)
        for host in DANBOORU_MIRRORS
    ]


def _request_booru_response(
    operations: CatalogSearchOperations,
    config: dict[str, Any],
    site: str,
    headers: dict,
    params: dict,
    auth: tuple[str, str] | None,
    throttle: Callable[[float], Any],
) -> tuple[Any | None, str, Exception | None]:
    urls = _booru_urls(config, site)
    response, used, last_error = None, urls[0], None
    for url in urls:
        for attempt in range(2 if len(urls) > 1 else 3):
            throttle()
            try:
                response = operations.request_get(
                    url,
                    timeout=25,
                    headers=headers,
                    params=params,
                    auth=auth,
                )
                used = url
                break
            except operations.request_errors as error:
                last_error, response = error, None
                operations.sleep(1.0 * (attempt + 1))
        if response is not None:
            break
    return response, used, last_error


def _booru_http_error(
    config: dict[str, Any],
    site: str,
    response: Any,
) -> dict | None:
    if response.status_code == 429:
        message = f"{config['name']} 요청 제한(429) — 잠시 뒤 다시 해 보세요."
    elif response.status_code == 451:
        message = f"{config['name']} 은 이 지역에서 막혀 있습니다 (451)."
    elif response.status_code in (401, 403):
        message = (
            f"{config['name']} 인증 실패({response.status_code}) "
            "— 관리 → API 의 '부루 계정' 을 확인해 주세요. "
            f"{BOORU_AUTH_HELP.get(site, '')}"
        )
    elif response.status_code == 422 and "TagLimit" in response.text:
        message = (
            f"{config['name']} 태그 개수 제한(422) — 계정 등급이 "
            "낮으면 태그 2개까지만 됩니다. 태그를 줄여 보세요."
        )
    elif response.status_code != 200:
        message = (
            f"{config['name']} HTTP {response.status_code}: "
            f"{response.text[:100]}"
        )
    else:
        return None
    return {"ok": False, "error": message}


def _booru_posts(response: Any, config: dict[str, Any]) -> list:
    try:
        data = response.json()
    except ValueError as error:
        raise ValueError(
            f"{config['name']} 이 JSON 을 주지 않았습니다 "
            "(API 키가 필요할 수 있음). 단부루로 검색해 보세요."
        ) from error
    posts = (
        data.get("post", [])
        if isinstance(data, dict) and "post" in data
        else data
    )
    if isinstance(posts, dict):
        posts = posts.get("posts", [])
    return posts


def _booru_page_base(
    config: dict[str, Any],
    site: str,
    used: str,
) -> str:
    page_base = config["page"]
    if site == "danbooru":
        used_host = used.split("/")[2]
        if used_host != DANBOORU_MIRRORS[0]:
            page_base = page_base.replace(
                DANBOORU_MIRRORS[0],
                used_host,
            )
    return page_base


def _booru_item(
    site: str,
    post: dict[str, Any],
    page_base: str,
) -> dict[str, Any] | None:
    if site == "e621":
        file_info = post.get("file") or {}
        preview_info = post.get("preview") or {}
        tag_text = " ".join(sum(
            (
                (post.get("tags") or {}).get(group) or []
                for group in (
                    "artist",
                    "character",
                    "copyright",
                    "general",
                    "species",
                )
            ),
        ))
        thumb = preview_info.get("url")
        full = file_info.get("url")
    elif site == "gelbooru":
        tag_text = post.get("tags") or ""
        thumb = post.get("preview_url")
        full = post.get("file_url")
    else:
        tag_text = post.get("tag_string") or ""
        thumb = post.get("preview_file_url") or post.get("large_file_url")
        full = post.get("file_url") or post.get("large_file_url")
    if not thumb:
        return None
    return {
        "id": post.get("id"),
        "tags": tag_text,
        "artist": (post.get("tag_string_artist") or "").strip(),
        "character": (post.get("tag_string_character") or "").strip(),
        "copyright": (post.get("tag_string_copyright") or "").strip(),
        "thumb": thumb,
        "full": full,
        "rating": post.get("rating", ""),
        "score": post.get("score", 0),
        "url": (
            f"{page_base}/{post.get('id')}"
            if site != "gelbooru"
            else f"{page_base}&id={post.get('id')}"
        ),
    }


def search_booru(
    paths: CatalogSearchPaths,
    state: CatalogSearchState,
    operations: CatalogSearchOperations,
    site: str = "danbooru",
    tags: str = "",
    page: int = 1,
    limit: int = 40,
    *,
    credentials: Callable[[str], tuple[str, str]] | None = None,
    throttle: Callable[[float], Any] | None = None,
) -> dict[str, Any]:
    """사이트별 API 응답을 공통 이미지 카드 결과로 정규화한다."""
    config = BOORUS.get(site) or BOORUS["danbooru"]
    credential_lookup = credentials or (
        lambda wanted_site: booru_creds(paths, state, wanted_site)
    )
    throttle_call = throttle or (
        lambda gap=1.0: booru_throttle(state, operations, gap)
    )
    tags, note = _normalize_booru_tags(
        site,
        tags,
        credential_lookup,
    )
    headers, params, auth, credential_error = _booru_request_options(
        config,
        site,
        tags,
        page,
        limit,
        credential_lookup,
        operations.user_agent,
    )
    if credential_error is not None:
        return credential_error
    try:
        response, used, last_error = _request_booru_response(
            operations,
            config,
            site,
            headers,
            params,
            auth,
            throttle_call,
        )
        if response is None:
            operations.log_warning(
                f"{site} 검색 연결 실패: {last_error}"
            )
            extra = (
                " 미러(hijiribe·sonohara)도 응답하지 않았습니다."
                if site == "danbooru"
                else ""
            )
            return {
                "ok": False,
                "error": (
                    f"{config['name']} 이 연결을 끊었습니다 — 검색을 "
                    "너무 자주 보내면 잠시 막습니다. 1~2분 뒤 다시 "
                    f"해 보세요.{extra}"
                ),
            }
        http_error = _booru_http_error(config, site, response)
        if http_error is not None:
            return http_error
        try:
            posts = _booru_posts(response, config)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
    except Exception as error:
        return {
            "ok": False,
            "error": f"{config['name']} 검색 실패: {error}",
        }

    urls = _booru_urls(config, site)
    if site == "danbooru" and used != urls[0]:
        host = used.split("/")[2]
        note = (
            (note + " · " if note else "")
            + f"본 도메인이 막혀 미러({host})로 검색했습니다"
        )
        operations.log_info(f"단부루 미러 사용: {host}")
    page_base = _booru_page_base(config, site, used)
    items = [
        item
        for item in (
            _booru_item(site, post, page_base)
            for post in (posts or [])
        )
        if item is not None
    ]
    return {
        "ok": True,
        "site": site,
        "name": config["name"],
        "count": len(items),
        "items": items,
        "page": page,
        "note": note,
        "search_url": (
            f"{page_base}?tags={tags.replace(' ', '+')}"
            if site != "gelbooru"
            else f"{page_base}&tags={tags}"
        ),
    }


def nai_tag_key(raw: Any) -> str:
    """가중치·강조·artist 접두사를 걷어 NAI 개명표 대조 키를 만든다."""
    tag = str(raw or "").strip().lower()
    for _attempt in range(4):
        match = re.fullmatch(
            r"[+-]?\d+(?:\.\d+)?\s*::(.*?)::",
            tag,
        )
        if not match:
            break
        tag = match.group(1).strip()
    tag = tag.translate(str.maketrans("", "", "{}[]")).strip()
    tag = re.sub(r"^artists?:", "", tag)
    return re.sub(
        r"_+",
        "_",
        re.sub(r"\s+", "_", tag),
    ).strip("_")


def nai_renamed_tag(raw: Any) -> str | None:
    """단부루 표기가 NAI에서 바뀌었으면 NAI 권장 이름을 반환한다."""
    return NAI_RENAMED_TAGS.get(nai_tag_key(raw))


def tagv_norm(raw: Any) -> str:
    """프롬프트 표기를 단부루 검증용 이름으로 바꾸고 조각 참조는 제외한다."""
    tag = (raw or "").strip()
    if not tag or tag.startswith("#"):
        return ""
    renamed_key = nai_tag_key(tag)
    if renamed_key in NAI_RENAMED_TAGS:
        return renamed_key
    if tag.startswith("<") and tag.endswith(">"):
        return ""
    for _attempt in range(4):
        match = re.fullmatch(
            r"[+-]?\d+(?:\.\d+)?\s*::(.*?)::",
            tag.strip(),
        )
        if not match:
            break
        tag = match.group(1)
    tag = (
        tag.translate(str.maketrans("", "", "{}[]"))
        .strip()
        .lower()
    )
    tag = re.sub(r"^artists?:", "", tag)
    return re.sub(
        r"_+",
        "_",
        re.sub(r"\s+", "_", tag),
    ).strip("_")


def tags_json_at(
    state: CatalogSearchState,
    operations: CatalogSearchOperations,
    endpoint: str,
    params: dict[str, Any],
    *,
    throttle: Callable[[float], Any] | None = None,
) -> list[dict[str, Any]]:
    """단부루 목록 API를 본 도메인과 미러 순서로 호출한다."""
    throttle_call = throttle or (
        lambda gap=1.0: booru_throttle(state, operations, gap)
    )
    last = None
    for host in DANBOORU_MIRRORS:
        throttle_call(0.4)
        try:
            response = operations.request_get(
                f"https://{host}/{endpoint}",
                params=params,
                timeout=20,
                headers={
                    "User-Agent": operations.user_agent,
                    "Accept": "application/json",
                },
            )
            if response.status_code == 200:
                data = response.json()
                return data if isinstance(data, list) else []
            last = f"HTTP {response.status_code}"
        except operations.request_errors + (ValueError,) as error:
            last = type(error).__name__
    raise RuntimeError(last or "실패")


def tags_json(
    state: CatalogSearchState,
    operations: CatalogSearchOperations,
    params: dict[str, Any],
    *,
    fetch_at: Callable[[str, dict[str, Any]], list[dict[str, Any]]]
    | None = None,
) -> list[dict[str, Any]]:
    """tags.json 호출을 별칭 API와 같은 주입 가능 경계로 연결한다."""
    caller = fetch_at or (
        lambda endpoint, values: tags_json_at(
            state,
            operations,
            endpoint,
            values,
        )
    )
    return caller("tags.json", params)


def _normalize_verification_tags(
    text: str,
) -> tuple[dict[str, str], list[str]]:
    seen: dict[str, str] = {}
    order: list[str] = []
    semicolon_tag = "\x00NAI_SEMICOLON_BAR\x00"
    prepared = (text or "").replace(";|", semicolon_tag)
    parts = (
        prepared.replace(chr(10), ",")
        .replace(";", ",")
        .replace(semicolon_tag, ";|")
        .split(",")
    )
    for chunk in parts:
        normalized = tagv_norm(chunk)
        if not normalized or normalized in seen:
            continue
        seen[normalized] = chunk.strip()
        order.append(normalized)
    return seen, order


def _refresh_tag_cache(
    state: CatalogSearchState,
    order: list[str],
    fetch_tags: Callable[[dict[str, Any]], list[dict[str, Any]]],
) -> str | None:
    todo = [
        tag
        for tag in order
        if tag not in NAI_RENAMED_TAGS
        and tag not in state.tag_cache
    ]
    for index in range(0, len(todo), 40):
        batch = todo[index:index + 40]
        try:
            found_rows = fetch_tags({
                "search[name_space]": " ".join(batch),
                "limit": 200,
            })
        except RuntimeError as error:
            return str(error)
        found = {
            str(item.get("name")): (
                int(item.get("post_count") or 0),
                bool(item.get("is_deprecated")),
            )
            for item in found_rows
        }
        for tag in batch:
            state.tag_cache[tag] = found.get(tag)
    return None


def _missing_verification_tags(
    state: CatalogSearchState,
    order: list[str],
) -> list[str]:
    return [
        tag
        for tag in order
        if tag not in NAI_RENAMED_TAGS
        if (
            state.tag_cache.get(tag, (1, False)) is None
            or state.tag_cache.get(tag, (1, False))[0] == 0
        )
    ]


def _load_tag_aliases(
    missing: list[str],
    fetch_at: Callable[[str, dict[str, Any]], list[dict[str, Any]]],
) -> dict[str, tuple[str, str]]:
    aliases: dict[str, tuple[str, str]] = {}
    for index in range(0, len(missing), 30):
        batch = missing[index:index + 30]
        try:
            rows = fetch_at(
                "tag_aliases.json",
                {
                    "search[antecedent_name_space]": " ".join(batch),
                    "limit": 200,
                },
            )
        except RuntimeError:
            break
        for item in rows:
            antecedent = str(item.get("antecedent_name"))
            consequent = str(item.get("consequent_name"))
            current = aliases.get(antecedent)
            if current is None or (
                item.get("status") == "active"
                and current[1] != "active"
            ):
                aliases[antecedent] = (
                    consequent,
                    str(item.get("status") or ""),
                )
    return aliases


def _ghost_suggestions(
    tag: str,
    fetch_tags: Callable[[dict[str, Any]], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    try:
        suggestions = fetch_tags({
            "search[name_matches]": f"*{tag}*",
            "search[order]": "count",
            "limit": 5,
        })
        return [
            {
                "name": str(suggestion.get("name")),
                "count": int(suggestion.get("post_count") or 0),
            }
            for suggestion in suggestions
            if suggestion.get("name")
            and str(suggestion.get("name")) != tag
            and int(suggestion.get("post_count") or 0) > 0
        ]
    except RuntimeError:
        return []


def _verification_item(
    state: CatalogSearchState,
    seen: dict[str, str],
    aliases: dict[str, tuple[str, str]],
    tag: str,
    low: int,
    fetch_tags: Callable[[dict[str, Any]], list[dict[str, Any]]],
) -> dict[str, Any]:
    if tag in NAI_RENAMED_TAGS:
        return {
            "raw": seen[tag],
            "tag": tag,
            "count": None,
            "status": "nai_renamed",
            "alias_to": NAI_RENAMED_TAGS[tag],
        }
    if tag not in state.tag_cache:
        return {
            "raw": seen[tag],
            "tag": tag,
            "count": None,
            "status": "unknown",
        }
    record = state.tag_cache[tag]
    count, deprecated = (0, False) if record is None else record
    if count >= low:
        status = "ok"
    elif count > 0:
        status = "low"
    elif tag in aliases:
        consequent, alias_status = aliases[tag]
        return {
            "raw": seen[tag],
            "tag": tag,
            "count": 0,
            "status": "alias",
            "alias_to": consequent,
            "alias_status": alias_status,
        }
    elif deprecated:
        status = "old"
    else:
        status = "ghost"
    item: dict[str, Any] = {
        "raw": seen[tag],
        "tag": tag,
        "count": count,
        "status": status,
    }
    if deprecated:
        item["deprecated"] = True
    if status == "ghost":
        item["suggest"] = _ghost_suggestions(tag, fetch_tags)
    return item


def _verification_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    return {
        status: sum(
            1 for item in items if item["status"] == status
        )
        for status in (
            "ok",
            "low",
            "old",
            "alias",
            "nai_renamed",
            "ghost",
            "unknown",
        )
    }


def verify_tags(
    state: CatalogSearchState,
    operations: CatalogSearchOperations,
    text: str,
    low: int = 100,
    *,
    fetch_tags: Callable[[dict[str, Any]], list[dict[str, Any]]]
    | None = None,
    fetch_at: Callable[[str, dict[str, Any]], list[dict[str, Any]]]
    | None = None,
) -> dict[str, Any]:
    """태그 존재·희소·폐지·별칭·NAI 개명 상태와 오타 후보를 반환한다.

    legacy 공개 wrapper는 ``fetch_tags=_tags_json``과
    ``fetch_at=_tags_json_at``을 넘겨 기존 monkeypatch 지점을 보존한다.
    """
    tag_fetch = fetch_tags or (
        lambda params: tags_json(state, operations, params)
    )
    endpoint_fetch = fetch_at or (
        lambda endpoint, params: tags_json_at(
            state,
            operations,
            endpoint,
            params,
        )
    )
    seen, order = _normalize_verification_tags(text)
    error_message = _refresh_tag_cache(state, order, tag_fetch)
    missing = _missing_verification_tags(state, order)
    aliases = _load_tag_aliases(missing, endpoint_fetch)
    result = [
        _verification_item(
            state,
            seen,
            aliases,
            tag,
            low,
            tag_fetch,
        )
        for tag in order
    ]
    return {
        "ok": True,
        "items": result,
        "error": error_message,
        "summary": _verification_summary(result),
    }


__all__ = [
    "BOORUS",
    "BOORU_AUTH_HELP",
    "CatalogSearchOperations",
    "CatalogSearchPaths",
    "CatalogSearchState",
    "DANBOORU_MIRRORS",
    "DANBOORU_SFW_MIRROR",
    "NAI_RENAMED_TAGS",
    "booru_creds",
    "booru_throttle",
    "nai_renamed_tag",
    "nai_tag_key",
    "search_booru",
    "tags_json",
    "tags_json_at",
    "tagv_norm",
    "verify_tags",
]
