# -*- coding: utf-8 -*-
"""실행 coordinator가 공유하는 중단 신호."""


class FatalStopError(Exception):
    """인증·계정 오류처럼 현재 실행을 즉시 끝내야 할 때 사용한다."""


__all__ = ["FatalStopError"]
