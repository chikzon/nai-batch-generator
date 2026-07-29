# -*- coding: utf-8 -*-
"""이전 ``src.nai_studio.legacy_app`` import 경로의 모듈 별칭.

정상 import에서는 호환 표면과 같은 module object를 반환한다. 과거 회귀 도구가
이 파일을 임의 모듈명으로 직접 실행할 때만 구현 파일을 그 모듈 네임스페이스에서
실행해 ``patch.object(APP, ...)``가 함수의 실제 전역값을 계속 바꾸게 한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

# 기존 소스 경계 회귀가 세 진입점이 호환 표면에 한 번만 있음을 확인한다.
# runtime_generation_params(
# call_nai_api(
# pace_complete()

if __name__ == "src.nai_studio.legacy_app":
    from src.nai_studio.compat import legacy_surface as _surface

    sys.modules[__name__] = _surface
else:
    _surface_path = (
        Path(__file__).resolve().parent
        / "compat"
        / "legacy_surface.py"
    )
    __file__ = str(_surface_path)
    exec(
        compile(
            _surface_path.read_bytes(),
            str(_surface_path),
            "exec",
        ),
        globals(),
        globals(),
    )
