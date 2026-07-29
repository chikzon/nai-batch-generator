# -*- coding: utf-8 -*-
"""생성 작업의 메모리 상태와 실행권 관리."""
from __future__ import annotations

import copy
import io
import threading
import time
from typing import Any, Callable, Mapping


class LiveState:
    """HTTP 미리보기와 worker가 공유하는 한 실행의 상태 저장소.

    장부 저장 함수는 호출자가 주입한다. 이 모듈은 사용자 경로나 NAI 호출을 모르며,
    이중 시작 방지·중지·진행률·미리보기 바이트만 소유한다.
    """

    def __init__(
        self,
        persist_jobs: bool = False,
        *,
        daily_cap: int = 0,
        start_job: Callable[..., str] | None = None,
        finish_job: Callable[..., Any] | None = None,
    ):
        self.lock = threading.Lock()
        self.image_bytes = None
        self.filename = ""
        self.char_name = ""
        self.index = 0
        self.total = 0
        self.daily = 0
        self.daily_cap = daily_cap
        self.status_text = "설정 중..."
        self.running = False
        self._owner = 0
        self.stop_req = False
        self.seed = 0
        self.seed_key = ""
        self.operation = "대기"
        self.phase = "idle"
        self.completed = 0
        self.failed = 0
        self.retry_count = 0
        self.last_error = ""
        self.can_retry = False
        self.retry_mode = "preview"
        self.started_at = 0.0
        self.finished_at = 0.0
        self.eta_base_completed = 0
        self.persist_jobs = bool(persist_jobs)
        self.job_id = ""
        self._blueprint_snapshot: dict[str, Any] = {}
        self._start_job = start_job
        self._finish_job = finish_job

    def update(self, **kwargs: Any) -> None:
        with self.lock:
            for key, value in kwargs.items():
                setattr(self, key, value)

    def note_retry(self, error: Any = "") -> None:
        with self.lock:
            self.retry_count += 1
            if error:
                self.last_error = str(error)

    def try_claim(
        self,
        operation: str = "생성",
        retry_mode: str = "preview",
        *,
        blueprint: Mapping[str, Any] | None = None,
        payload_identity: Mapping[str, Any] | None = None,
    ) -> int | None:
        """실행권을 원자 선점하고, 이미 작업 중이면 None을 반환."""
        with self.lock:
            if self.running:
                return None
            self.running = True
            self.stop_req = False
            self._owner += 1
            self.operation = str(operation or "생성")
            self.phase = "running"
            self.completed = 0
            self.failed = 0
            self.retry_count = 0
            self.last_error = ""
            self.can_retry = False
            self.retry_mode = str(retry_mode or "preview")
            self.started_at = time.time()
            self.finished_at = 0.0
            self.eta_base_completed = 0
            self._blueprint_snapshot = copy.deepcopy(
                blueprint if isinstance(blueprint, dict) else {})
            if self.persist_jobs:
                if self._start_job is None:
                    raise RuntimeError("작업 장부 시작 콜백이 없습니다.")
                self.job_id = self._start_job(
                    self.operation,
                    self.retry_mode,
                    blueprint=blueprint,
                    payload_identity=payload_identity,
                )
            return self._owner

    def frozen_blueprint(self) -> dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self._blueprint_snapshot)

    def release(self, token: int) -> None:
        """선점 토큰이 일치할 때만 실행권과 장부를 닫는다."""
        with self.lock:
            if self._owner != token:
                return
            if self.stop_req and self.phase in ("running", "stopping"):
                self.phase = "stopped"
                self.can_retry = True
            elif self.phase in ("running", "stopping"):
                self.phase = "completed"
            self.finished_at = time.time()
            self.running = False
            self.stop_req = False
            if self.persist_jobs:
                if self._finish_job is None:
                    raise RuntimeError("작업 장부 종료 콜백이 없습니다.")
                self._finish_job(
                    self.job_id,
                    status=self.phase,
                    completed=self.completed,
                    failed=self.failed,
                    can_resume=self.can_retry,
                    message=self.status_text,
                )
                self.job_id = ""

    def wait_cancelable(self, seconds: float) -> bool:
        """최대 0.5초 간격으로 중지 요청을 확인하며 대기."""
        end = time.time() + max(0.0, float(seconds))
        while time.time() < end:
            if self.stop_req:
                return True
            time.sleep(min(0.5, end - time.time()))
        return self.stop_req

    def request_stop(self) -> bool:
        """실행권은 유지하고 worker가 다음 안전 지점에서 멈추도록 표시."""
        with self.lock:
            if not self.running:
                return False
            self.stop_req = True
            self.phase = "stopping"
            self.status_text = "중지 요청 — 이번 장까지 마치고 멈춥니다."
            return True

    def set_image(self, image: Any) -> None:
        buffer = io.BytesIO()
        image.save(buffer, "WEBP", quality=85)
        with self.lock:
            self.image_bytes = buffer.getvalue()
            seed = getattr(image, "nai_seed", None)
            if seed:
                self.seed = int(seed)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            end = (
                time.time()
                if self.running
                else (self.finished_at or self.started_at or 0.0)
            )
            elapsed = (
                max(0.0, end - self.started_at) if self.started_at else 0.0)
            run_done = max(
                0, int(self.completed) - int(self.eta_base_completed))
            remaining = max(
                0, int(self.total) - int(self.completed) - int(self.failed))
            eta = None
            if self.running and run_done > 0 and remaining > 0:
                eta = elapsed / run_done * remaining
            elif self.phase == "completed" and self.total:
                eta = 0.0
            return {
                "filename": self.filename,
                "char_name": self.char_name,
                "index": self.index,
                "total": self.total,
                "daily": self.daily,
                "daily_cap": self.daily_cap,
                "status_text": self.status_text,
                "running": self.running,
                "stopping": self.stop_req,
                "has_image": self.image_bytes is not None,
                "seed": self.seed,
                "seed_key": self.seed_key,
                "operation": self.operation,
                "phase": self.phase,
                "completed": self.completed,
                "failed": self.failed,
                "retry_count": self.retry_count,
                "last_error": self.last_error,
                "can_retry": self.can_retry,
                "retry_mode": self.retry_mode,
                "job_id": self.job_id,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "elapsed_seconds": round(elapsed, 1),
                "eta_seconds": round(eta, 1) if eta is not None else None,
                "eta_samples": run_done,
            }

    def image(self) -> bytes | None:
        with self.lock:
            return self.image_bytes


__all__ = ["LiveState"]
