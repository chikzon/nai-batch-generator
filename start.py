# -*- coding: utf-8 -*-
"""기존 NAI 작업실 실행·import 경로를 유지하는 호환 진입점."""

from src.nai_studio import legacy_app as _implementation


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


if __name__ == "__main__":
    _implementation.main()
