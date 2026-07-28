# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""아카라이브 공개 게시글을 공통 임포트로 넘기기 위한 작은 어댑터.

수집 결과를 별도 데이터베이스에 가두지 않는다. 이 모듈은 공개 목록·게시글을
읽어 URL과 설명만 돌려주며, 중복 판정·이미지 보관·되돌리기는 start.py의 공통
임포트 경계가 맡는다.
"""

from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
import re
import time

import requests


ARCA_BASE_URL = "https://arca.live"
ARCA_BOARD_PATH = "/b/aiart"
DEFAULT_KEYWORD = "그림체 공유"
MAX_PAGES = 100
MAX_IMAGE_BYTES = 64 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class PublicImportError(RuntimeError):
    pass


def _classes(attrs):
    return set((dict(attrs).get("class") or "").split())


def _safe_url(value, base=ARCA_BASE_URL, image=False):
    raw = str(value or "").strip()
    if not raw:
        return ""
    url = urljoin(base, raw)
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return ""
    host = (parsed.hostname or "").lower()
    allowed = (
        host == "arca.live"
        or (
            image
            and (
                host.endswith(".arca.live")
                or host == "ac.namu.la"
                or host.endswith(".namu.la")
            )
        )
    )
    if not allowed:
        return ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))


def normalize_article_url(value):
    url = _safe_url(value)
    parsed = urlparse(url)
    match = re.fullmatch(r"/b/aiart/(\d+)/?", parsed.path)
    if not match:
        raise PublicImportError(
            "https://arca.live/b/aiart/숫자 형식의 공개 게시글 주소가 필요합니다."
        )
    return f"{ARCA_BASE_URL}{ARCA_BOARD_PATH}/{match.group(1)}"


class _CategoryParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.current = {"href": dict(attrs).get("href", ""), "text": []}

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.links.append(
                (self.current["href"], " ".join(self.current["text"]).strip())
            )
            self.current = None


class _SearchParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.depth = 0
        self.roles = []
        self.results = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = _classes(attrs)
        if self.current is None:
            if tag == "a" and {"vrow", "column"} <= classes and "notice" not in classes:
                self.current = {
                    "href": attributes.get("href", ""),
                    "title": [],
                    "badge": [],
                    "posted_at": "",
                }
                self.depth = 1
                self.roles = [None]
            return
        if tag in VOID_TAGS:
            return
        self.depth += 1
        self.roles.append(
            "title" if "title" in classes else ("badge" if "badge" in classes else None)
        )
        if tag == "time" and attributes.get("datetime"):
            self.current["posted_at"] = attributes["datetime"][:10]

    def handle_data(self, data):
        if self.current is None or not data.strip():
            return
        if "title" in self.roles:
            self.current["title"].append(data)
        elif "badge" in self.roles:
            self.current["badge"].append(data)

    def handle_endtag(self, tag):
        if self.current is None:
            return
        if tag == "a" and self.depth == 1:
            self.results.append(self.current)
            self.current = None
            self.depth = 0
            self.roles = []
            return
        if self.roles:
            self.roles.pop()
        self.depth = max(0, self.depth - 1)


class _ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.depth = 0
        self.found = False
        self.tags = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        if not self.active:
            if tag == "div" and "article-content" in _classes(attrs):
                self.active = True
                self.found = True
                self.depth = 1
            return
        attributes = dict(attrs)
        self.tags.append((tag, attributes))
        if tag not in VOID_TAGS:
            self.depth += 1

    def handle_data(self, data):
        if self.active and data.strip():
            self.text.append(data.strip())

    def handle_endtag(self, tag):
        if not self.active or tag in VOID_TAGS:
            return
        self.depth -= 1
        if self.depth <= 0:
            self.active = False


def discover_category_params(html):
    parser = _CategoryParser()
    parser.feed(str(html or ""))
    result = {}
    for href, text in parser.links:
        url = _safe_url(href)
        if not url or urlparse(url).path.rstrip("/") != ARCA_BOARD_PATH:
            continue
        params = dict(parse_qsl(urlparse(url).query))
        label = " ".join(text.split())
        if label == "NAI":
            result["NAI"] = params
        elif "NAI" in label and ("🔞" in label or "R18" in label.upper()):
            result["R18_NAI"] = params
    return result


def build_search_url(keyword, page, category_params=None):
    try:
        page = int(page)
    except (TypeError, ValueError):
        raise PublicImportError("페이지는 숫자여야 합니다.")
    if not 1 <= page <= MAX_PAGES:
        raise PublicImportError(f"페이지는 1~{MAX_PAGES} 범위여야 합니다.")
    keyword = str(keyword or DEFAULT_KEYWORD).strip()
    if not keyword or len(keyword) > 200:
        raise PublicImportError("검색어를 확인해 주세요.")
    query = dict(category_params or {})
    query.update({"target": "title_content", "keyword": keyword, "p": page})
    return urlunparse(("https", "arca.live", ARCA_BOARD_PATH, "", urlencode(query), ""))


def extract_search_results(html, keyword=DEFAULT_KEYWORD):
    parser = _SearchParser()
    parser.feed(str(html or ""))
    required = [word.casefold() for word in str(keyword).split() if word]
    rows, seen = [], set()
    for raw in parser.results:
        title = " ".join("".join(raw["title"]).split())
        if not title or not all(word in title.casefold() for word in required):
            continue
        url = _safe_url(raw.get("href"))
        match = re.match(r"^https://arca\.live/b/aiart/(\d+)", url)
        if not match:
            continue
        url = f"{ARCA_BASE_URL}{ARCA_BOARD_PATH}/{match.group(1)}"
        if url in seen:
            continue
        seen.add(url)
        badge = " ".join("".join(raw["badge"]).split())
        tab = "R18_NAI" if "🔞" in badge and "NAI" in badge else (
            "NAI" if "NAI" in badge else ""
        )
        if not tab:
            continue
        rows.append(
            {
                "source_url": url,
                "article_id": match.group(1),
                "title": title,
                "board_tab": tab,
                "posted_at": raw.get("posted_at") or "",
            }
        )
    return rows


def _image_candidates(tags, article_url):
    result, seen = [], set()

    def add(value):
        url = _safe_url(value, article_url, image=True)
        if not url:
            return
        parsed = urlparse(url)
        if parsed.hostname == "ac.namu.la":
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            query["type"] = "orig"
            url = urlunparse(parsed._replace(query=urlencode(query)))
        identity = urlunparse(parsed._replace(query=""))
        if identity not in seen:
            seen.add(identity)
            result.append(url)

    for tag, attrs in tags:
        if tag == "img":
            # 현재 아카라이브는 `data-originalurl`에 EXIF가 남은 원본을,
            # `src`에는 화면용 축소본을 둔다. 둘 다 넣으면 같은 그림을 두 번 받는다.
            add(
                attrs.get("data-originalurl")
                or attrs.get("data-original")
                or attrs.get("data-src")
                or attrs.get("src")
            )
        elif tag == "source":
            for part in (attrs.get("srcset") or "").split(","):
                add(part.strip().split(" ")[0])
        elif tag == "a" and re.search(
            r"\.(png|jpe?g|webp)(?:\?|$)", attrs.get("href", ""), re.I
        ):
            add(attrs.get("href"))
    return result


def extract_article(html, article_url):
    article_url = normalize_article_url(article_url)
    html = str(html or "")
    parser = _ArticleParser()
    parser.feed(html)
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""
    text = "\n".join(parser.text)
    date_match = re.search(r"(20\d{2}-\d{2}-\d{2})", html)
    article_id = article_url.rstrip("/").split("/")[-1]
    return {
        "source_url": article_url,
        "article_id": article_id,
        "title": title,
        "posted_at": date_match.group(1) if date_match else "",
        "body_text": text,
        "image_urls": _image_candidates(parser.tags, article_url),
    }


def create_session():
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.6",
        }
    )
    return session


def fetch_text(session, url, attempts=3):
    safe = _safe_url(url)
    if not safe:
        raise PublicImportError("허용되지 않은 게시글 주소입니다.")
    error = None
    for attempt in range(max(1, int(attempts))):
        try:
            response = session.get(safe, timeout=(10, 30))
            if not _safe_url(response.url):
                raise PublicImportError("게시글 요청이 허용되지 않은 주소로 이동했습니다.")
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "html" not in content_type:
                raise PublicImportError("게시글이 HTML로 응답하지 않았습니다.")
            return response.text
        except (requests.RequestException, PublicImportError) as exc:
            error = exc
            if attempt + 1 < attempts:
                time.sleep(0.8 * (attempt + 1))
    raise PublicImportError(f"게시글을 읽지 못했습니다: {error}")


def fetch_image(session, url):
    safe = _safe_url(url, image=True)
    if not safe:
        raise PublicImportError("허용되지 않은 이미지 주소입니다.")
    with session.get(safe, timeout=(10, 45), stream=True) as response:
        if not _safe_url(response.url, image=True):
            raise PublicImportError("이미지 요청이 허용되지 않은 주소로 이동했습니다.")
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type not in {"image/png", "image/webp", "image/jpeg"}:
            raise PublicImportError("PNG/WebP/JPEG 이미지가 아닙니다.")
        claimed = int(response.headers.get("content-length") or 0)
        if claimed > MAX_IMAGE_BYTES:
            raise PublicImportError("이미지가 64MB를 넘습니다.")
        chunks, total = [], 0
        for chunk in response.iter_content(256 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                raise PublicImportError("이미지가 64MB를 넘습니다.")
            chunks.append(chunk)
        return b"".join(chunks), content_type
