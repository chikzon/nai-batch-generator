# -*- coding: utf-8 -*-
"""배포 전 로컬 smoke 검증.

GitHub Actions도 이 파일만 호출한다. 검증 규칙을 CI 안에 따로 복제하지 않아 로컬과
원격의 통과 기준이 어긋나지 않게 한다. NovelAI API나 사용자 토큰은 사용하지 않는다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def run(label, *args):
    print(f"\n■ {label}")
    result = subprocess.run(
        [sys.executable, *map(str, args)],
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        raise SystemExit(result.returncode)


def main():
    run(
        "Python 구문",
        "-m", "py_compile",
        ROOT / "start.py",
        ROOT / "src" / "nai_studio" / "legacy_app.py",
        ROOT / "src" / "nai_studio" / "runtime" / "logging_config.py",
        ROOT / "src" / "nai_studio" / "runtime" / "diagnostics.py",
        ROOT / "빌드.py",
        ROOT / "배포준비.py",
        ROOT / "tools" / "build" / "app.py",
        ROOT / "tools" / "build" / "distribution.py",
        ROOT / "contracts" / "chatbot-nai" / "validate_contract.py",
    )
    run(
        "챗봇↔NAI 연결 계약",
        ROOT / "tests" / "contracts" / "test_chatbot_nai_contract.py",
    )
    run(
        "모듈 경계 호환",
        ROOT / "tests" / "architecture" / "test_module_boundaries.py",
    )
    run("무과금 회귀", ROOT / "tests" / "regression" / "test_legacy_app.py")
    print("\n✔ 배포 전 smoke 검증 통과")


if __name__ == "__main__":
    main()
