# -*- coding: utf-8 -*-
"""NAI 작업실의 로깅 경계.

실행 앱은 프로필의 ``생성.log``를 쓰고, 검증 프로세스는 ``NAI_LOG_FILE``로
격리 경로를 주입한다. 도메인·서비스 모듈은 파일 핸들러를 직접 만들지 않는다.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import TextIO


LOG_FILE_ENV = "NAI_LOG_FILE"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOGGER_NAME = "gen"


def resolve_application_log_path(default: str | Path) -> Path:
    """환경 주입 경로가 있으면 사용하고, 없으면 프로필 기본 경로를 돌려준다."""
    injected = str(os.environ.get(LOG_FILE_ENV) or "").strip()
    return Path(injected).expanduser() if injected else Path(default)


def configure_application_logging(
    log_file: str | Path,
    *,
    stream: TextIO | None = None,
) -> logging.Logger:
    """앱 전용 logger를 파일과 stdout에 한 번만 연결한다.

    root logger를 바꾸지 않아 라이브러리 로그와 앱 로그의 생명주기를 분리한다.
    같은 프로세스에서 모듈을 다시 불러오면 이전 앱 핸들러만 닫고 교체한다.
    """
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    close_application_logging(logger)

    formatter = logging.Formatter(LOG_FORMAT)
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler._nai_managed = True
    logger.addHandler(file_handler)

    console = logging.StreamHandler(stream or sys.stdout)
    console.setFormatter(formatter)
    console._nai_managed = True
    logger.addHandler(console)
    return logger


def close_application_logging(logger: logging.Logger) -> None:
    """이 모듈이 붙인 handler만 닫는다."""
    for handler in list(logger.handlers):
        if getattr(handler, "_nai_managed", False):
            logger.removeHandler(handler)
            handler.close()


__all__ = [
    "LOG_FILE_ENV",
    "close_application_logging",
    "configure_application_logging",
    "resolve_application_log_path",
]
