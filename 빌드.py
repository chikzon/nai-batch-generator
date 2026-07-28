#!/usr/bin/env python
# -*- coding: utf-8 -*-
# NAI 배치 생성기 — Copyright (C) 2026 ninesdead
# GPL-3.0-or-later. 이 프로그램은 어떠한 보증도 없이 제공됩니다.
"""단독 실행형 Windows 앱으로 묶는다 (PyInstaller).

왜 이 방식인가 — 우리 구조는 **파이썬 단일 파일 + 브라우저 UI** 다.
Electron·Tauri 를 얹으면 껍데기 하나 때문에 100~200MB 가 붙고 구조가 통째로 바뀐다.
PyInstaller 는 지금 구조를 **그대로 두고** 파이썬 런타임만 함께 넣는다.
`실행.bat` 이 인터넷에서 파이썬을 내려받던 것을 **exe 안에 넣는 것**이 이 빌드의 목적이다.

    python 빌드.py              # 본체 폴더 + 별도 기본자료팩.zip
    python 빌드.py --설치본      # 위 + 본체만 든 설치 프로그램(.exe)
    python 빌드.py --정리        # build/dist/생성물 삭제

⚠ 프로그램 자산만 exe **옆**에 둔다 (`_internal` 안이 아니라).
   설치 실행본의 사용자 데이터(`설정.json`·`output/`)는
   `%LOCALAPPDATA%\\NAI배치생성기\\데이터`에 쌓여 제거·재설치와 분리된다.
   `--portable`을 명시한 경우에만 exe 옆을 쓴다.
   후보사전·태그·세팅 같은 내용물은 `기본자료팩.zip`으로 따로 만든다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# ⚠ 윈도우 기본 콘솔은 cp949 라 `—`·`✔` 에서 UnicodeEncodeError 로 죽는다.
#   start.py 와 같은 처리를 여기도 해 둔다 (실제로 한 번 겪었다).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
APP_NAME = "NAI배치생성기"
APP_VERSION = "1.0.0"
PUBLISHER = "ninesdead"

# exe 옆에 놓을 **프로그램 자산**. 후보·태그·세팅 등 내용물은 넣지 않는다.
ASSETS = [
    "t5_tokenizer.json",
    "README.md", "LICENSE", "CREDITS.md", "THIRD_PARTY_NOTICES.md",
    "requirements.txt",
]
# HTML 안에 다시 CSS를 쌓지 않고 화면 구성 자산을 프로그램과 함께 둔다.
# 개인 자료가 아니라 실행에 필요한 코드 자산이므로 exe 옆에 반드시 복사한다.
ASSET_DIRS: list[str] = ["ui"]

# 사용자가 원할 때 자료 탭으로 넣는 **별도 기본 자료팩**.
# `asset_config.json`은 세팅 3종의 구형 중복본이라 넣지 않는다. 둘을 함께 넣으면
# 세팅을 뺐는데도 첫 실행 마이그레이션이 다시 만들어 내는 원인이 된다.
DATA_PACK_ASSETS = ["후보사전.json", "규격.json", "옵션.json"]
DATA_PACK_DIRS = ["태그", "세팅"]
DATA_PACK_NAME = f"{APP_NAME}-기본자료팩.zip"


def _run(cmd: list[str], **kw) -> int:
    print("  $", " ".join(str(c) for c in cmd[:6]), "…" if len(cmd) > 6 else "")
    return subprocess.call(cmd, **kw)


ICON_SRC = "아이콘용이미지.png"      # 있으면 이걸로 만든다. 없으면 격자 도형으로 대체
ICON_CUT = "build/_cut.png"        # rembg 로 배경을 뺀 것 (한 번 만들면 재사용)


def _icon_from_character(dst: Path) -> Path | None:
    """캐릭터 얼굴로 아이콘을 만든다 — 얼굴 크게 + 하늘 배경 + MM 식 굵은 둥근 테두리.

    ⚠ 크롭 좌표는 `아이콘용이미지.png`(832×1216) 에 맞춘 값이다. 다른 그림으로 바꾸면
      `CX`·`EYE_Y`·`SIDE` 를 다시 잡아야 한다. 눈이 정사각형의 42% 지점에 오게 뒀다
      (아이콘은 눈이 살짝 위에 있어야 얼굴로 읽힌다).
    ⚠ 배경 제거는 rembg `isnet-anime` 로 하고 **결과를 `build/_cut.png` 에 캐시**한다.
      모델 첫 로드가 오래 걸려서, 빌드마다 다시 하지 않는다.
    """
    from PIL import Image, ImageDraw, ImageFilter
    src = HERE / ICON_SRC
    if not src.is_file():
        return None
    cutp = HERE / ICON_CUT
    if not cutp.exists():
        try:
            from rembg import remove, new_session
            print("  배경 제거 중 (rembg isnet-anime — 첫 실행은 모델 내려받아 오래 걸린다)")
            cutp.parent.mkdir(exist_ok=True)
            remove(Image.open(src).convert("RGBA"),
                   session=new_session("isnet-anime")).save(cutp)
        except Exception as e:
            print(f"  ! 배경 제거 실패 — 원본 그대로 씁니다: {e}")
            cutp = src
    cut = Image.open(cutp).convert("RGBA")

    S, CX, EYE_Y, SIDE, EYE_R = 512, 415, 315, 390, 0.42
    RADIUS, BORDER, BCOLOR = 0.22, 20, (12, 14, 20)

    top = max(0, EYE_Y - int(SIDE * EYE_R))
    left = max(0, min(CX - SIDE // 2, cut.width - SIDE))
    face = cut.crop((left, top, left + SIDE, top + SIDE)).resize((S, S), Image.LANCZOS)

    # 망토 안감의 하늘 — 위는 맑게, 아래는 짙은 남색
    bg = Image.new("RGBA", (S, S))
    d = ImageDraw.Draw(bg)
    for y in range(S):
        t = y / (S - 1)
        a, b, u = ((196, 232, 253), (126, 190, 238), t / 0.55) if t < 0.55 else \
                  ((126, 190, 238), (30, 58, 110), (t - 0.55) / 0.45)
        d.line([(0, y), (S, y)], fill=tuple(int(a[i] + (b[i] - a[i]) * u) for i in range(3)) + (255,))
    # ⚠ 흰 후광은 넣지 않는다 — 인물 둘레에 흰 테가 생겨 지저분해진다 (사용자 지적).
    bg.alpha_composite(face)

    r = int(S * RADIUS)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=255)
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(bg, (0, 0), mask)
    # 테두리 — NAIS3-MM 처럼 굵게. 1px 씩 겹쳐 그려 둥근 모서리를 따라간다
    od = ImageDraw.Draw(out)
    for i in range(BORDER):
        od.rounded_rectangle([i, i, S - 1 - i, S - 1 - i],
                             radius=max(2, r - i), outline=BCOLOR + (255,), width=1)

    out.save(dst, format="ICO",
             sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"  아이콘 → {dst.name} (캐릭터 얼굴 · 테두리 {BORDER}px)")
    return dst


def make_icon(dst: Path) -> Path | None:
    """아이콘. 캐릭터 그림이 있으면 그걸 쓰고, 없으면 격자 도형으로 대체한다."""
    try:
        from PIL import Image, ImageDraw
    except Exception as e:
        print(f"  ! Pillow 없음 — 아이콘 없이 빌드합니다: {e}")
        return None
    try:
        got = _icon_from_character(dst)
        if got:
            return got
    except Exception as e:
        print(f"  ! 캐릭터 아이콘 실패 — 격자 도형으로 대체합니다: {e}")
    size = 256
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([8, 8, size - 8, size - 8], radius=44, fill=(30, 41, 59, 255))
    pad, gap = 46, 14
    cell = (size - pad * 2 - gap * 2) // 3
    accents = {(0, 0), (1, 1), (2, 2)}
    for r in range(3):
        for c in range(3):
            x, y = pad + c * (cell + gap), pad + r * (cell + gap)
            fill = (56, 189, 248, 255) if (r, c) in accents else (71, 85, 105, 255)
            d.rounded_rectangle([x, y, x + cell, y + cell], radius=8, fill=fill)
    im.save(dst, format="ICO",
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"  아이콘 → {dst.name} (대체 도형)")
    return dst


def make_version_file(dst: Path) -> Path:
    """Windows 파일 속성(버전·회사·제품명). exe 우클릭 → 속성에서 보인다."""
    v = APP_VERSION.split(".")
    while len(v) < 4:
        v.append("0")
    quad = ", ".join(v[:4])
    dst.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({quad}), prodvers=({quad}), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041204B0', [
      StringStruct('CompanyName', '{PUBLISHER}'),
      StringStruct('FileDescription', 'NAI 배치 생성기'),
      StringStruct('FileVersion', '{APP_VERSION}'),
      StringStruct('InternalName', '{APP_NAME}'),
      StringStruct('LegalCopyright', 'Copyright (C) 2026 {PUBLISHER}. GPL-3.0-or-later'),
      StringStruct('OriginalFilename', '{APP_NAME}.exe'),
      StringStruct('ProductName', 'NAI 배치 생성기'),
      StringStruct('ProductVersion', '{APP_VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1042, 1200])])
  ]
)
""", encoding="utf-8")
    print(f"  버전 리소스 → {dst.name}")
    return dst


def build_exe(icon: Path | None, verfile: Path) -> Path:
    out = HERE / "dist"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", APP_NAME,
        "--onedir",                     # onefile 은 매 실행마다 임시폴더에 풀어 느리다
        "--console",                    # 서버 로그·주소가 보여야 한다 (실행.bat 과 같은 경험)
        "--version-file", str(verfile),
        "--collect-submodules", "encodings",
        "--hidden-import", "PIL.Image",
        "--hidden-import", "PIL.ImageDraw",
        "--distpath", str(out),
        "--workpath", str(HERE / "build"),
        "--specpath", str(HERE / "build"),
    ]
    if icon:
        cmd += ["--icon", str(icon)]
    cmd.append(str(HERE / "start.py"))
    if _run(cmd) != 0:
        raise SystemExit("PyInstaller 실패")
    exe = out / APP_NAME / f"{APP_NAME}.exe"
    if not exe.exists():
        raise SystemExit(f"exe 가 안 나왔다: {exe}")
    return exe


def copy_assets(app_dir: Path) -> tuple[list[str], list[str]]:
    """자산을 exe 옆으로. BASE_DIR 이 이 자리를 보므로 코드 수정이 필요 없다."""
    put, miss = [], []
    for name in ASSETS:
        src = HERE / name
        if src.is_file():
            shutil.copy2(src, app_dir / name)
            put.append(name)
        else:
            miss.append(name)
    for name in ASSET_DIRS:
        src = HERE / name
        if src.is_dir():
            shutil.copytree(src, app_dir / name, dirs_exist_ok=True)
            put.append(name + "/")
        else:
            miss.append(name + "/")
    return put, miss


def build_data_pack(out_dir: Path, src_root: Path | None = None) -> Path:
    """기본 후보·태그·세팅을 본체와 섞지 않고 검증 가능한 ZIP 하나로 만든다.

    `src_root` 는 자료를 읽어올 자리다. 기본은 저장소 폴더(`HERE`)이므로 실제 빌드는
    예전과 똑같이 돈다. **시험에서 가짜 자료를 넣어 부르라고 열어 뒀다** —
    `태그/`·`t5_tokenizer.json` 은 남의 저작물이라 저장소에 없어서(`.gitignore`),
    `HERE` 만 보면 **새로 복제한 곳에서는 자료팩이 비어 시험이 깨진다.**
    """
    root_dir = Path(src_root) if src_root else HERE
    target = out_dir / DATA_PACK_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    payloads: dict[str, bytes] = {}
    for name in DATA_PACK_ASSETS:
        src = root_dir / name
        if src.is_file():
            payloads[name] = src.read_bytes()
    for name in DATA_PACK_DIRS:
        root = root_dir / name
        if not root.is_dir():
            continue
        for src in sorted(root.rglob("*")):
            if src.is_file() and "__pycache__" not in src.parts:
                payloads[src.relative_to(root_dir).as_posix()] = src.read_bytes()
    entries = [{
        "path": name,
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    } for name, raw in sorted(payloads.items())]
    fingerprint = hashlib.sha256("\n".join(
        f"{entry['path']}\t{entry['size']}\t{entry['sha256']}"
        for entry in entries
    ).encode("utf-8")).hexdigest()
    manifest = {
        "schema": "nais-datapack/v1",
        "id": f"basic-{APP_VERSION}-{fingerprint[:16]}",
        "name": "NAI 배치 생성기 기본 자료팩",
        "version": APP_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "content_sha256": fingerprint,
        "files": entries,
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as z:
        z.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"),
        )
        for name, raw in sorted(payloads.items()):
            z.writestr(name, raw)
        z.writestr(
            "기본자료팩-사용법.txt",
            "NAI 배치 생성기 기본 자료팩\n\n"
            "1. 프로그램을 실행합니다.\n"
            "2. [자료] → [자료 넣기]에 이 ZIP을 그대로 끌어다 놓습니다.\n"
            "3. 후보사전·규격·옵션·태그·세팅이 각각 제자리에 들어갑니다.\n\n"
            "본체에는 이 자료가 포함되지 않습니다. manifest.json의 파일별 SHA-256을 "
            "검사한 뒤 장착하며, 같은 팩을 다시 넣어도 기존 개인 자료를 덮어쓰지 않습니다. "
            "가져온 기록에서 이번에 추가한 자료만 해제할 수 있습니다.\n",
        )
    return target


def find_iscc() -> Path | None:
    """Inno Setup 컴파일러. ⚠ winget 이 **관리자 없이** 깔면 `Program Files` 가 아니라
    `%LOCALAPPDATA%\\Programs` 로 들어간다 (실제로 여기 깔렸다). 셋 다 본다."""
    cands = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ]
    for p in cands:
        if p.exists():
            return p
    w = shutil.which("iscc") or shutil.which("ISCC")
    return Path(w) if w else None


def write_iss(app_dir: Path, icon: Path | None) -> Path:
    """설치 프로그램 스크립트. 비교 프로젝트들과 같은 형식(사용자별 설치·바로가기·제거)."""
    iss = HERE / "build" / f"{APP_NAME}.iss"
    ico = f'SetupIconFile={icon}\n' if icon else ""
    iss.write_text(f"""; 자동 생성 — 빌드.py
[Setup]
AppId={{{{8F3A9C41-5B7E-4A2D-9E10-NAIBATCH0001}}}}
AppName=NAI 배치 생성기
AppVersion={APP_VERSION}
AppPublisher={PUBLISHER}
DefaultDirName={{localappdata}}\\Programs\\{APP_NAME}
DefaultGroupName=NAI 배치 생성기
UninstallDisplayName=NAI 배치 생성기
UninstallDisplayIcon={{app}}\\{APP_NAME}.exe
OutputDir={HERE / "dist"}
OutputBaseFilename={APP_NAME}-{APP_VERSION}-setup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
{ico}
[Languages]
Name: "korean"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{app_dir}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{group}}\\NAI 배치 생성기"; Filename: "{{app}}\\{APP_NAME}.exe"
Name: "{{userdesktop}}\\NAI 배치 생성기"; Filename: "{{app}}\\{APP_NAME}.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 작업:"

[Run]
Filename: "{{app}}\\{APP_NAME}.exe"; Description: "지금 실행"; Flags: nowait postinstall skipifsilent
""", encoding="utf-8")
    print(f"  설치 스크립트 → {iss.name}")
    return iss


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--설치본", action="store_true", help="설치 프로그램도 만든다 (Inno Setup 필요)")
    ap.add_argument("--정리", action="store_true", help="build/dist 삭제")
    a = ap.parse_args()

    if a.정리:
        for d in ("build", "dist"):
            shutil.rmtree(HERE / d, ignore_errors=True)
        print("정리 완료")
        return 0

    print(f"■ {APP_NAME} {APP_VERSION} 빌드")
    (HERE / "build").mkdir(exist_ok=True)
    icon = make_icon(HERE / "build" / "icon.ico")
    verfile = make_version_file(HERE / "build" / "version.txt")

    print("■ PyInstaller")
    exe = build_exe(icon, verfile)
    app_dir = exe.parent

    print("■ 자산 복사 (exe 옆 — BASE_DIR 이 보는 자리)")
    put, miss = copy_assets(app_dir)
    print(f"  넣음 {len(put)}개: {', '.join(put)}")
    if miss:
        print(f"  없어서 건너뜀 {len(miss)}개: {', '.join(miss)}")

    total = sum(f.stat().st_size for f in app_dir.rglob("*") if f.is_file())
    print(f"\n✔ exe: {exe}")
    print(f"  폴더 크기: {total/1024/1024:.1f} MB · 항목 {sum(1 for _ in app_dir.rglob('*'))}개")

    print("■ 기본 자료팩 (본체와 분리)")
    data_pack = build_data_pack(HERE / "dist")
    print(f"✔ 자료팩: {data_pack} ({data_pack.stat().st_size/1024/1024:.1f} MB)")

    if a.설치본:
        print("■ 설치 프로그램")
        iss = write_iss(app_dir, icon)
        iscc = find_iscc()
        if not iscc:
            print("  ! Inno Setup(ISCC.exe) 이 없다. 스크립트만 만들어 뒀다.")
            print("    설치: winget install -e --id JRSoftware.InnoSetup")
            print(f"    이후: \"{iscc or 'ISCC.exe'}\" \"{iss}\"")
        elif _run([str(iscc), str(iss)]) == 0:
            setup = HERE / "dist" / f"{APP_NAME}-{APP_VERSION}-setup.exe"
            print(f"\n✔ 설치본: {setup}"
                  + (f" ({setup.stat().st_size/1024/1024:.1f} MB)" if setup.exists() else " (경로 확인 필요)"))
        else:
            print("  ! ISCC 실패")
    return 0


if __name__ == "__main__":
    sys.exit(main())
