# -*- coding: utf-8 -*-
"""구형 공개 수집 import 경로를 유지하는 호환 어댑터.

새 코드는 ``src.nai_studio.collection.arca``를 사용한다. 기존 start.py와 외부
스크립트가 ``import arca_public_import``를 계속 써도 같은 객체를 받는다.
"""

from src.nai_studio.collection import arca as _implementation


__all__ = [
    name for name in vars(_implementation)
    if not name.startswith("__")
]
globals().update({
    name: getattr(_implementation, name)
    for name in __all__
})


def __getattr__(name):
    return getattr(_implementation, name)

