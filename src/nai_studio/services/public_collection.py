# -*- coding: utf-8 -*-
"""공개자료 발견·재개·임포트를 조정하는 서비스."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from src.nai_studio.collection import arca
from src.nai_studio.domain.restoration import summarize_restore_queue
from src.nai_studio.runtime.data_files import atomic_write_json, load_json_recover
from src.nai_studio.services.legacy_bridge import (
    evidence_from_image_record,
    style_asset_from_record,
)
from src.nai_studio.services.restoration_inputs import (
    public_collection_queue,
    public_collection_summary,
)


StyleRecordFactory = Callable[[bytes, str, Mapping[str, Any]], dict | None]
LocalImageImporter = Callable[[bytes, str, str], tuple[str, bool]]
StyleImporter = Callable[..., dict]


class PublicCollectionManager:
    """수집 진행을 보존하고 확인된 이미지 기록을 공통 임포트로 전달한다."""

    def __init__(
        self,
        state_file: str | Path,
        *,
        style_record_from_image: StyleRecordFactory,
        local_import_image: LocalImageImporter,
        add_style_record: StyleImporter,
    ):
        self.state_file = Path(state_file)
        self._style_record_from_image = style_record_from_image
        self._local_import_image = local_import_image
        self._add_style_record = add_style_record
        self.lock = threading.RLock()
        self.thread: threading.Thread | None = None
        self.load_error = ""
        self.state = self._load_state()

    @staticmethod
    def _empty() -> dict:
        return {
            "schema": "nais-public-collection/v2",
            "status": "idle",
            "stage": "idle",
            "keyword": arca.DEFAULT_KEYWORD,
            "pages": 2,
            "max_posts": 100,
            "direct_urls": [],
            "queue": [],
            "cursor": 0,
            "found_posts": 0,
            "scanned_posts": 0,
            "scanned_images": 0,
            "metadata_images": 0,
            "added": 0,
            "updated": 0,
            "existing": 0,
            "skipped": 0,
            "errors": [],
            "new_posts": 0,
            "changed_posts": 0,
            "unchanged_posts": 0,
            "failed_posts": 0,
            "articles": {},
            "failures": {},
            "current": "",
            "started_at": "",
            "updated_at": "",
            "finished_at": "",
        }

    def _load_state(self) -> dict:
        state = self._empty()
        if not self.state_file.is_file():
            return state
        try:
            saved = load_json_recover(self.state_file)
            if isinstance(saved, dict):
                state.update(saved)
        except Exception as exc:
            self.load_error = str(exc)
            return state
        state["schema"] = "nais-public-collection/v2"
        if not isinstance(state.get("errors"), list):
            state["errors"] = []
        if state.get("status") in {"running", "pausing", "stopping"}:
            state.update(status="interrupted", stage="interrupted", current="")
        if not isinstance(state.get("articles"), dict):
            state["articles"] = {}
        if not isinstance(state.get("failures"), dict):
            state["failures"] = {}
        return state

    def _save_locked(self) -> None:
        self.state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.state_file, self.state, indent=1)

    def snapshot(self) -> dict:
        with self.lock:
            data = copy.deepcopy(self.state)
            data["ok"] = True
            data["can_resume"] = (
                data.get("status") in {"paused", "interrupted", "failed"}
                and int(data.get("cursor") or 0) < len(data.get("queue") or [])
            )
            data["failed_items"] = sorted(
                (
                    copy.deepcopy(value)
                    for value in (data.get("failures") or {}).values()
                    if isinstance(value, dict) and value.get("url")
                ),
                key=lambda value: str(value.get("failed_at") or ""),
                reverse=True,
            )
            data["can_retry_failed"] = bool(data["failed_items"])
            data["restoration"] = public_collection_summary(data)
            return data

    def restoration_snapshot(self) -> dict:
        """상태 polling과 분리해 사용자가 열 때만 전체 복원 큐를 만든다."""
        with self.lock:
            queue = public_collection_queue(copy.deepcopy(self.state))
        return {
            "ok": True,
            "restoration": summarize_restore_queue(queue),
            "restoration_queue": queue,
        }

    def _fresh_job(
        self,
        *,
        status: str,
        stage: str,
        queue: list[str],
        direct_urls: list[str] | None = None,
        keyword: str | None = None,
        pages: int = 0,
        max_posts: int = 100,
    ) -> dict:
        """수집 이력과 미해결 실패를 지키고 이번 실행 계수만 새로 연다."""
        state = self._empty()
        state.update(
            {
                "status": status,
                "stage": stage,
                "keyword": str(
                    keyword or self.state.get("keyword") or arca.DEFAULT_KEYWORD
                ),
                "pages": int(pages or 0),
                "max_posts": int(max_posts or 100),
                "direct_urls": list(direct_urls or queue),
                "queue": list(queue),
                "found_posts": len(queue),
                "articles": copy.deepcopy(self.state.get("articles") or {}),
                "failures": copy.deepcopy(self.state.get("failures") or {}),
                "started_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        return state

    @staticmethod
    def _direct_urls(payload: Mapping[str, Any]) -> list[str]:
        raw = payload.get("urls") or payload.get("direct_urls") or []
        if isinstance(raw, str):
            raw = re.split(r"[\s,]+", raw)
        if not isinstance(raw, list):
            raise ValueError("게시글 주소 목록의 형식이 올바르지 않습니다.")
        result = []
        for value in raw:
            if not str(value or "").strip():
                continue
            url = arca.normalize_article_url(value)
            if url not in result:
                result.append(url)
        return result

    def _resume_locked(self) -> dict | None:
        if self.state.get("status") not in {"paused", "interrupted", "failed"}:
            return {"ok": False, "error": "이어갈 수집 작업이 없습니다."}
        if int(self.state.get("cursor") or 0) >= len(self.state.get("queue") or []):
            return {"ok": False, "error": "남은 게시글이 없습니다."}
        self.state.update(
            status="running", stage="downloading", errors=[], finished_at=""
        )
        return None

    def _new_job_locked(self, payload: Mapping[str, Any]) -> dict | None:
        keyword = str(payload.get("keyword") or arca.DEFAULT_KEYWORD).strip()
        if len(keyword) > 200:
            return {"ok": False, "error": "검색어는 200자 이하여야 합니다."}
        try:
            pages = max(0, min(20, int(payload.get("pages") or 0)))
            max_posts = max(1, min(1000, int(payload.get("max_posts") or 100)))
            direct_urls = self._direct_urls(payload)
        except (TypeError, ValueError, arca.PublicImportError) as exc:
            return {"ok": False, "error": str(exc)}
        if not direct_urls and not pages:
            return {
                "ok": False,
                "error": "게시글 주소를 넣거나 검색 페이지 수를 1 이상으로 정해 주세요.",
            }
        self.state = self._fresh_job(
            status="running",
            stage="searching",
            queue=direct_urls,
            direct_urls=direct_urls,
            keyword=keyword,
            pages=pages,
            max_posts=max_posts,
        )
        return None

    def _launch_locked(self, name: str) -> None:
        self._save_locked()
        self.thread = threading.Thread(target=self._run, name=name, daemon=True)
        self.thread.start()

    def start(self, payload: Mapping[str, Any] | None = None, resume: bool = False) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        with self.lock:
            if self.load_error:
                return {
                    "ok": False,
                    "error": "공개자료 수집 진행 기록이 손상되어 저장을 멈췄습니다. "
                    "공개자료수집-진행.json과 .bak을 확인하세요.",
                }
            if self.thread and self.thread.is_alive():
                if resume and self.state.get("status") == "paused":
                    self.state.update(status="running", stage="downloading")
                    self._save_locked()
                    return self.snapshot()
                return {"ok": False, "error": "공개자료 수집이 이미 진행 중입니다."}
            error = self._resume_locked() if resume else self._new_job_locked(payload)
            if error:
                return error
            self._launch_locked("public-material-import")
            return self.snapshot()

    def retry_failed(self, payload: Mapping[str, Any] | None = None) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        with self.lock:
            if self.load_error:
                return {
                    "ok": False,
                    "error": "공개자료 수집 진행 기록이 손상되어 재시도를 멈췄습니다.",
                }
            if self.thread and self.thread.is_alive():
                return {"ok": False, "error": "공개자료 수집이 이미 진행 중입니다."}
            failures = self.state.get("failures") or {}
            raw = payload.get("urls") or []
            if isinstance(raw, str):
                raw = re.split(r"[\s,]+", raw)
            if not isinstance(raw, list):
                return {"ok": False, "error": "재시도할 게시글 목록이 올바르지 않습니다."}
            selected = []
            for value in raw:
                try:
                    url = arca.normalize_article_url(value)
                except arca.PublicImportError as exc:
                    return {"ok": False, "error": str(exc)}
                if url in failures and url not in selected:
                    selected.append(url)
            if not selected:
                return {"ok": False, "error": "실패 목록에서 재시도할 게시글을 고르세요."}
            self.state = self._fresh_job(
                status="running",
                stage="downloading",
                queue=selected,
                direct_urls=selected,
                pages=0,
                max_posts=max(len(selected), 1),
            )
            self.state["retrying_failed"] = True
            self._launch_locked("public-material-retry")
            return self.snapshot()

    def control(self, action: str) -> dict:
        action = str(action or "").lower()
        if action == "resume":
            return self.start(resume=True)
        with self.lock:
            if not self.thread or not self.thread.is_alive():
                return {"ok": False, "error": "진행 중인 수집 작업이 없습니다."}
            if action == "pause":
                self.state.update(status="paused", stage="paused")
            elif action == "stop":
                self.state.update(status="stopping", stage="stopping")
            else:
                return {
                    "ok": False,
                    "error": "pause, resume, stop 중 하나가 필요합니다.",
                }
            self._save_locked()
            return self.snapshot()

    def _checkpoint(self) -> bool:
        while True:
            with self.lock:
                status = self.state.get("status")
                if status == "stopping":
                    self.state.update(
                        status="stopped",
                        stage="stopped",
                        current="",
                        finished_at=datetime.now().isoformat(timespec="seconds"),
                    )
                    self._save_locked()
                    return False
                if status != "paused":
                    return True
            time.sleep(0.25)

    def _record_failure(
        self, url: str, error: Any, article: Mapping[str, Any] | None = None
    ) -> None:
        with self.lock:
            failures = self.state.setdefault("failures", {})
            prior = failures.get(url) if isinstance(failures.get(url), dict) else {}
            failures[url] = {
                "url": url,
                "article_id": str(
                    (article or {}).get("article_id") or url.rstrip("/").split("/")[-1]
                ),
                "title": str((article or {}).get("title") or prior.get("title") or ""),
                "error": str(error)[:500],
                "attempts": int(prior.get("attempts") or 0) + 1,
                "failed_at": datetime.now().isoformat(timespec="seconds"),
            }
            self.state["failed_posts"] = int(self.state.get("failed_posts") or 0) + 1
            errors = self.state.setdefault("errors", [])
            errors.append(f"{url}: {str(error)[:400]}")
            del errors[:-20]
            self._save_locked()

    @staticmethod
    def _article_digest(article: Mapping[str, Any]) -> str:
        stable = {
            "title": str(article.get("title") or ""),
            "body_text": str(article.get("body_text") or ""),
            "image_urls": list(article.get("image_urls") or []),
        }
        return hashlib.sha256(
            json.dumps(
                stable,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def _remember_article(
        self,
        article: Mapping[str, Any],
        digest: str,
        classification: str,
        metadata_images: int,
        evidence_refs: list[str] | None = None,
    ) -> None:
        url = str(article.get("source_url") or "")
        with self.lock:
            prior = (self.state.get("articles") or {}).get(url) or {}
            self.state.setdefault("articles", {})[url] = {
                "url": url,
                "article_id": str(article.get("article_id") or ""),
                "title": str(article.get("title") or "")[:200],
                "posted_at": str(article.get("posted_at") or ""),
                "content_sha256": digest,
                "image_count": len(article.get("image_urls") or []),
                "metadata_images": int(metadata_images or 0),
                "evidence_refs": list(
                    evidence_refs
                    if evidence_refs is not None
                    else prior.get("evidence_refs") or []
                ),
                "last_seen": datetime.now().isoformat(timespec="seconds"),
            }
            key = {
                "new": "new_posts",
                "changed": "changed_posts",
                "unchanged": "unchanged_posts",
            }[classification]
            self.state[key] = int(self.state.get(key) or 0) + 1
            self.state.setdefault("failures", {}).pop(url, None)
            self._save_locked()

    def _discover(self, session: Any) -> None:
        with self.lock:
            pages = int(self.state.get("pages") or 0)
            keyword = self.state.get("keyword") or arca.DEFAULT_KEYWORD
            max_posts = int(self.state.get("max_posts") or 100)
            queue = list(self.state.get("queue") or [])
        if not pages:
            return
        board_html = arca.fetch_text(session, arca.ARCA_BASE_URL + arca.ARCA_BOARD_PATH)
        category = (arca.discover_category_params(board_html).get("NAI") or {})
        for page in range(1, pages + 1):
            if not self._checkpoint():
                return
            rows = arca.extract_search_results(
                arca.fetch_text(session, arca.build_search_url(keyword, page, category)),
                keyword,
            )
            if not rows:
                break
            for row in rows:
                article_url = row["source_url"]
                if article_url not in queue:
                    queue.append(article_url)
                if len(queue) >= max_posts:
                    break
            with self.lock:
                self.state.update(
                    queue=queue,
                    found_posts=len(queue),
                    current=f"검색 {page}/{pages}페이지",
                )
                self._save_locked()
            if len(queue) >= max_posts:
                break
            time.sleep(0.7)

    def _set_current_image(
        self, article: Mapping[str, Any], image_index: int, image_count: int
    ) -> None:
        with self.lock:
            self.state["current"] = (
                f"{article.get('title') or article['article_id']} · "
                f"이미지 {image_index}/{image_count}"
            )
            self._save_locked()

    def _import_image(
        self,
        session: Any,
        article: Mapping[str, Any],
        image_url: str,
    ) -> str | None:
        data, content_type = arca.fetch_image(session, image_url)
        return self._ingest_image_bytes(article, data, content_type, image_url)

    def _ingest_image_bytes(
        self,
        article: Mapping[str, Any],
        data: bytes,
        content_type: str,
        origin_url: str,
    ) -> str | None:
        """받은 바이트를 기존 수집 계약(증거·그림체·이미지캐시)으로 들여온다.

        네트워크 수집(_import_image)과 브라우저 relay가 같은 경로를 쓴다.
        """
        record = self._style_record_from_image(data, content_type, article)
        with self.lock:
            self.state["scanned_images"] += 1
        if record is None:
            with self.lock:
                self.state["skipped"] += 1
                self._save_locked()
            return None
        local_ref, created = self._local_import_image(
            data, content_type, origin_url)
        record["images"] = [local_ref]
        record["content_sha256"] = hashlib.sha256(data).hexdigest()
        evidence_record = evidence_from_image_record(record)
        record["evidence_records"] = [evidence_record]
        record["knowledge_asset"] = style_asset_from_record(
            record,
            evidence_refs=[evidence_record["id"]],
            lifecycle="candidate",
        )
        filename = local_ref[6:]
        detail = self._add_style_record(
            record,
            import_info={
                "kind": "crawler",
                "file": article["source_url"],
                "files": {"수집/이미지캐시": [filename]} if created else {},
            },
            return_detail=True,
        )
        with self.lock:
            self.state["metadata_images"] += 1
            action = detail.get("action")
            if action in {"added", "updated", "existing"}:
                self.state[action] += 1
            self._save_locked()
        return evidence_record["id"]

    def relay_article(
        self,
        source_url: str,
        html_text: str,
        images: list[tuple[bytes, str]],
    ) -> dict:
        """브라우저가 전달한 게시물 하나를 기존 수집 계약 그대로 들여온다.

        네트워크를 쓰지 않는다 — HTML과 이미지 바이트는 사용자가 브라우저에서
        고른 것이다. 진행·중복 판정·증거 기록은 수집과 같은 상태 파일을 쓴다.
        """
        url = arca.normalize_article_url(source_url)
        article = arca.extract_article(html_text, url)
        article["board_tab"] = "NAI"
        digest = self._article_digest(article)
        with self.lock:
            previous = copy.deepcopy(
                (self.state.get("articles") or {}).get(url) or {}
            )
        classification = "changed" if previous else "new"
        if (
            previous.get("content_sha256") == digest
            and int(previous.get("metadata_images") or 0)
        ):
            metadata_images = int(previous.get("metadata_images") or 0)
            self._remember_article(article, digest, "unchanged", metadata_images)
            return {
                "ok": True,
                "classification": "unchanged",
                "metadata_images": metadata_images,
                "url": url,
            }
        evidence_refs, image_errors = [], []
        for image_index, (data, content_type) in enumerate(images, 1):
            try:
                evidence_ref = self._ingest_image_bytes(
                    article, data, content_type, url)
                if evidence_ref:
                    evidence_refs.append(evidence_ref)
            except Exception as exc:
                image_errors.append(
                    f"이미지 {image_index}/{len(images)}: {exc}")
        self._remember_article(
            article,
            digest,
            classification,
            len(evidence_refs),
            evidence_refs=evidence_refs,
        )
        return {
            "ok": not image_errors,
            "classification": classification,
            "metadata_images": len(evidence_refs),
            "url": url,
            "errors": image_errors,
        }

    def _article_version(
        self, session: Any, url: str
    ) -> tuple[dict, str, dict, str]:
        article = arca.extract_article(arca.fetch_text(session, url), url)
        article["board_tab"] = "NAI"
        digest = self._article_digest(article)
        with self.lock:
            previous = copy.deepcopy(
                (self.state.get("articles") or {}).get(url) or {}
            )
        classification = "changed" if previous else "new"
        return article, digest, previous, classification

    def _import_article(self, session: Any, url: str) -> dict:
        article, digest, previous, classification = self._article_version(session, url)
        if previous.get("content_sha256") == digest:
            metadata_images = int(previous.get("metadata_images") or 0)
            self._remember_article(article, digest, "unchanged", metadata_images)
            return {
                "ok": True,
                "classification": "unchanged",
                "metadata_images": metadata_images,
                "article": article,
            }
        evidence_refs, image_errors = [], []
        image_urls = article.get("image_urls") or []
        for image_index, image_url in enumerate(image_urls, 1):
            if not self._checkpoint():
                return {
                    "ok": False,
                    "stopped": True,
                    "classification": classification,
                    "article": article,
                }
            self._set_current_image(article, image_index, len(image_urls))
            try:
                evidence_ref = self._import_image(session, article, image_url)
                if evidence_ref:
                    evidence_refs.append(evidence_ref)
            except Exception as exc:
                image_errors.append(f"이미지 {image_index}/{len(image_urls)}: {exc}")
        if image_errors:
            return {
                "ok": False,
                "classification": classification,
                "metadata_images": len(evidence_refs),
                "article": article,
                "error": " · ".join(image_errors),
            }
        self._remember_article(
            article,
            digest,
            classification,
            len(evidence_refs),
            evidence_refs=evidence_refs,
        )
        return {
            "ok": True,
            "classification": classification,
            "metadata_images": len(evidence_refs),
            "article": article,
        }

    def _run_queue(self, session: Any) -> bool:
        while True:
            if not self._checkpoint():
                return False
            with self.lock:
                cursor = int(self.state.get("cursor") or 0)
                queue = list(self.state.get("queue") or [])
            if cursor >= len(queue):
                return True
            url = queue[cursor]
            try:
                result = self._import_article(session, url)
                if result.get("stopped"):
                    return False
                if not result.get("ok"):
                    self._record_failure(
                        url,
                        result.get("error") or "게시글 수집 실패",
                        result.get("article"),
                    )
            except Exception as exc:
                self._record_failure(url, exc)
            with self.lock:
                self.state["cursor"] = cursor + 1
                self.state["scanned_posts"] = cursor + 1
                self._save_locked()
            time.sleep(0.8)

    def _finish(self) -> None:
        with self.lock:
            partial = int(self.state.get("failed_posts") or 0) > 0
            status = "partial" if partial else "completed"
            self.state.update(
                status=status,
                stage=status,
                current="",
                finished_at=datetime.now().isoformat(timespec="seconds"),
            )
            self._save_locked()

    def _fail(self, error: Exception) -> None:
        with self.lock:
            self.state.update(
                status="failed",
                stage="failed",
                current="",
                finished_at=datetime.now().isoformat(timespec="seconds"),
            )
            self.state.setdefault("errors", []).append(str(error)[:500])
            self._save_locked()

    def _run(self) -> None:
        session = arca.create_session()
        try:
            self._discover(session)
            with self.lock:
                if self.state.get("status") in {"stopped", "stopping"}:
                    return
                self.state.update(stage="downloading", current="")
                self._save_locked()
            if self._run_queue(session):
                self._finish()
        except Exception as exc:
            self._fail(exc)
        finally:
            session.close()


__all__ = ["PublicCollectionManager"]
