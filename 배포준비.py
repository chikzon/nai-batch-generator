# -*- coding: utf-8 -*-
"""기존 배포 준비 명령을 유지하는 호환 진입점."""

from tools.build import distribution as _implementation


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
    raise SystemExit(_implementation.main())
