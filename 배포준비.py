# -*- coding: utf-8 -*-
# NAI 배치 생성기 — Copyright (C) 2026 ninesdead
# GPL-3.0-or-later. 자세한 조건은 LICENSE 파일을 보십시오.
"""
남에게 줄 배포본 만들기 — 내 설정·토큰·생성물을 뺀 깨끗한 사본을 ZIP으로.

  python 배포준비.py                 # 바탕화면에 ZIP 생성
  python 배포준비.py --out D:\어디    # 위치 지정
  python 배포준비.py --folder        # ZIP 대신 폴더로

내 작업 폴더는 건드리지 않는다. 사본을 만들어서 거기서 지운다.

■ 빠지는 것 (내 개인 데이터)
   설정.json · 설정.txt의 토큰/그림체/네거티브/캐릭터 · 상태.json · 생성.log
   수집/바이브/ (내 바이브·캐릭터 레퍼런스 원본과 인코딩)
   output/ · 캐릭터/ 내 캐릭터 · 그림체/ 내 프리셋 · 프로필/ · .git
   __pycache__ · *.덮어쓰기전백업 · *.bak · 개인 zip 파일
   **세팅/ · 씬규격/ · asset_config.json** (내가 만든 씬 데이터 — 필수가 아님)
   **수집물(그림체.json·작가통계.json·레시피.json·이미지캐시/)** — 남들이 공개한
   프롬프트 조합·예시 그림 모음이라 본 배포본에는 넣지 않는다 (라운드02 결정)
■ 들어가는 것 (남이 바로 쓸 수 있는 자산)
   start.py · 실행.bat · 태그/ · 후보사전.json · 규격.json · 옵션.json · README.md

세팅을 함께 주고 싶으면 `세팅/*.json` 만 따로 건네면 된다 (받는 쪽에서 세팅/ 에 넣으면 끝).
수집 자료를 주고 싶으면 `python 배포준비.py --자료팩` 으로 자료팩.zip 을 따로 만든다
(받는 쪽은 압축을 풀어 나온 수집/ 폴더를 앱 폴더에 덮어넣으면 라이브러리가 채워진다).
"""
import argparse
import json
import os
import re
import shutil
import stat
import sys
import zipfile
from pathlib import Path


def force_rmtree(path):
    """읽기 전용 파일(.git 객체 등)도 지워지는 rmtree.
    Windows 에서 git 객체는 읽기 전용이라 일반 rmtree 가 조용히 실패한다 —
    그 탓에 사본에 .git 이 남은 채 검사를 통과한 적이 있다 (라운드02 실측)."""
    def _onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=_onerror)

sys.stdout.reconfigure(encoding="utf-8")
SRC = Path(__file__).resolve().parent

# 통째로 뺄 것 (폴더/파일 이름)
#   세팅/·씬규격/·asset_config.json 은 전부 '내가 만든 씬 데이터'다.
#   (앱은 세팅/ 이 없으면 씬규격/ → asset_config.json 순으로 되살리므로 셋 다 빼야 한다)
#   남에게 줄 때는 세팅 없이 시작하고, 필요하면 세팅 파일만 따로 건네면 된다.
DROP_NAMES = {"__pycache__", "output", "생성.log", "설정.json", "상태.json",
              "generation_state.json", "nsfw_seed_state.json", "배포준비.py", ".git",
              # 프로필/ 은 계정별 설정·토큰·생성물 전체 — 통째로 뺀다
              # (안의 설정.json 등이 이름 규칙으로 걸리긴 하지만 이름에 기대지 않는다)
              "프로필",
              "세팅", "씬규격", "asset_config.json",
              # 씬 모드 목록도 내가 만든 데이터다 (앱이 없으면 빈 목록으로 시작)
              "씬.json",
              # 선별·즐겨찾기는 내 생성물에 붙은 이름표라 남에게 갈 이유가 없다
              "선별.json",
              # 수집물 — 남들이 공개한 프롬프트 조합·예시 그림. 본 배포본에서 제외하고
              # `--자료팩` 으로 따로 만든다 (앱은 이 파일들이 없어도 조용히 빈 채로 돈다)
              "그림체.json", "작가통계.json", "레시피.json", "이미지캐시",
              # 작가조합.json 은 그림체.json 의 구세대 판 — 같은 수집물이다
              "작가조합.json"}
DROP_SUFFIX = (".덮어쓰기전백업", ".log", ".pyc", ".pickle", ".tmp", ".bak")
# 사용자 콘텐츠라 비우는 폴더 (폴더 자체는 남김)
#   조각/ 은 와일드카드 — 내 조각을 남에게 딸려 보내지 않는다
CLEAR_DIRS = ["그림체", "수집/바이브", "조각"]
# 설정.txt 에서 값을 비울 항목 (캐릭터 이름은 캐릭터 파일과 함께 빠지므로 같이 비움)
BLANK_KEYS = ["토큰", "그림체", "네거티브", "여자", "남자",
              "캐릭터", "남자캐릭터", "파트너캐릭터"]


def should_drop(p: Path, root: Path) -> bool:
    if p.name in DROP_NAMES:
        return True
    if p.name.endswith(DROP_SUFFIX):
        return True
    # 최상위에 있는 개인 zip (프로젝트 자산이 아님)
    if p.suffix.lower() == ".zip" and p.parent == root:
        return True
    return False


def copy_ignore(directory, names):
    """개인 자료는 사본에 복사한 뒤 지우지 말고 처음부터 건너뛴다.

    `clean()`과 `verify()`는 복사 중 예외·새 파일 규칙에 대비한 이중 방어로 그대로 둔다.
    """
    parent = Path(directory)
    ignored = set()
    try:
        parent_rel = parent.resolve().relative_to(SRC)
    except ValueError:
        parent_rel = Path()
    clear_roots = {Path(rel) for rel in CLEAR_DIRS}
    inside_clear = any(
        parent_rel == root or root in parent_rel.parents
        for root in clear_roots
    )
    inside_characters = parent_rel == Path("캐릭터")
    for name in names:
        p = parent / name
        if should_drop(p, SRC):
            ignored.add(name)
        elif inside_clear:
            ignored.add(name)
        elif inside_characters and name != "규격_설명.txt":
            ignored.add(name)
    return ignored


def blank_settings_txt(path: Path):
    """설정.txt 를 '값은 비고 설명은 남은' 템플릿으로."""
    if not path.exists():
        return
    out, in_char_section = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        # [여자 사사] 같은 캐릭터 섹션부터는 통째로 버림
        if re.match(r"^\[(여자|남자)\s", stripped):
            in_char_section = True
            continue
        if in_char_section:
            if stripped.startswith("#") or not stripped:
                in_char_section = False
            else:
                continue
        m = re.match(r"^([^#=]+?)\s*=\s*(.*)$", line)
        if m and m.group(1).strip() in BLANK_KEYS:
            out.append(f"{m.group(1).strip()} = ")
            continue
        out.append(line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def clean(dst: Path):
    removed = 0
    for p in sorted(dst.rglob("*"), key=lambda x: -len(x.parts)):
        if should_drop(p, dst):
            try:
                force_rmtree(p) if p.is_dir() else p.unlink()
                removed += 1
            except OSError:
                pass
    for rel in CLEAR_DIRS:
        d = dst / rel
        if d.exists():
            for f in d.glob("*"):
                try:
                    shutil.rmtree(f) if f.is_dir() else f.unlink()
                    removed += 1
                except OSError:
                    pass
            d.mkdir(exist_ok=True)
    blank_settings_txt(dst / "설정.txt")

    # 캐릭터/ 는 설명 파일만 남긴다
    ch = dst / "캐릭터"
    if ch.exists():
        for f in ch.glob("*"):
            if f.name != "규격_설명.txt":
                try:
                    shutil.rmtree(f) if f.is_dir() else f.unlink()
                    removed += 1
                except OSError:
                    pass
    return removed


def verify(dst: Path):
    """개인 정보가 남지 않았는지 확인."""
    problems = []
    if (dst / "설정.json").exists():
        problems.append("설정.json 이 남아 있음")
    for backup in dst.rglob("*.bak"):
        if backup.is_file():
            problems.append(f"{backup.relative_to(dst)} 백업 파일이 남아 있음")
    txt = dst / "설정.txt"
    if txt.exists():
        for line in txt.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([^#=]+?)\s*=\s*(.+)$", line)
            if m and m.group(1).strip() in BLANK_KEYS and m.group(2).strip():
                problems.append(f"설정.txt 의 '{m.group(1).strip()}' 에 값이 남아 있음")
    # 토큰 문자열 흔적 — json 만 보면 설정.txt·bat·py 의 잔재를 놓친다.
    # 작은 텍스트 파일 전부를 본다 (라운드02 검토 반영).
    # ⚠ start.py 의 안내문("pst-..." 자리표시)이 걸리지 않게 **실제 토큰 모양**만 잡는다:
    #   pst- 뒤에 영숫자·-·_ 가 20자 이상 이어지는 것 (진짜 토큰은 60자 이상)
    TOKEN_RE = re.compile(r"pst-[A-Za-z0-9_\-]{20,}")
    TEXT_SUFFIX = (".json", ".txt", ".md", ".py", ".bat", ".csv", ".html", ".js")
    for p in dst.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIX:
            continue
        if p.stat().st_size > 30 * 1024 * 1024:
            continue
        try:
            t = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if TOKEN_RE.search(t):
            problems.append(f"{p.relative_to(dst)} 에 NAI 토큰으로 보이는 문자열")
    # 프로필 폴더는 통째로 빠져야 한다
    if (dst / "프로필").exists():
        problems.append("프로필/ 이 남아 있음 (계정별 토큰·설정)")
    # .git 도 남으면 안 된다 (커밋 이력·이메일이 딸려 간다)
    if (dst / ".git").exists():
        problems.append(".git 이 남아 있음 (커밋 이력·git 설정)")
    # 수집물은 본 배포본에서 빠져야 한다 (자료팩으로만 전달)
    for rel in ("수집/그림체.json", "수집/작가통계.json", "수집/레시피.json",
                "수집/이미지캐시", "수집/작가조합.json"):
        if (dst / rel).exists():
            problems.append(f"{rel} 이(가) 남아 있음 (자료팩 전용)")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path.home() / "Desktop"))
    ap.add_argument("--folder", action="store_true", help="ZIP 대신 폴더로 남김")
    ap.add_argument("--자료팩", action="store_true",
                    help="수집 자료(그림체·작가통계·레시피·이미지캐시)만 따로 ZIP")
    a = ap.parse_args()

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if getattr(a, "자료팩"):
        # 본 배포본과 별도로 건네는 수집 자료 묶음.
        # 받는 쪽은 압축을 풀어 나온 수집/ 을 앱 폴더에 덮어넣으면 된다.
        zip_path = out_dir / "자료팩.zip"
        print("자료팩 압축 중...")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for rel in ("수집/그림체.json", "수집/작가통계.json", "수집/레시피.json"):
                p = SRC / rel
                if p.exists():
                    z.write(p, rel)
            cache = SRC / "수집" / "이미지캐시"
            if cache.exists():
                for f in sorted(cache.rglob("*")):
                    # 원격/ 은 실행 중 캐시라 넣지 않는다
                    if f.is_file() and "원격" not in f.relative_to(cache).parts:
                        z.write(f, Path("수집/이미지캐시") / f.relative_to(cache))
        print(f"완료 → {zip_path}  ({zip_path.stat().st_size/1024/1024:.0f} MB)")
        return 0
    work = out_dir / "NAI배치생성기"
    if work.exists():
        force_rmtree(work)

    print(f"사본 만드는 중... ({SRC.name} → {work})")
    shutil.copytree(SRC, work, ignore=copy_ignore)
    n = clean(work)
    print(f"개인 데이터 {n}건 제거")

    problems = verify(work)
    if problems:
        print("\n! 확인 필요:")
        for p in problems:
            print("   -", p)
        print("  (그대로 두면 남에게 전달됩니다)")
        return 1

    size = sum(f.stat().st_size for f in work.rglob("*") if f.is_file())
    files = sum(1 for f in work.rglob("*") if f.is_file())
    print(f"검사 통과 — 파일 {files:,}개 / {size/1024/1024:.0f} MB")

    if a.folder:
        print(f"\n완료 → {work}")
        return 0

    zip_path = out_dir / "NAI배치생성기.zip"
    print("압축 중...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(work.rglob("*")):
            if f.is_file():
                z.write(f, Path("NAI배치생성기") / f.relative_to(work))
    shutil.rmtree(work)
    print(f"\n완료 → {zip_path}  ({zip_path.stat().st_size/1024/1024:.0f} MB)")
    print("이 파일을 통째로 주면 됩니다. 받은 사람은 압축을 풀고 실행.bat 을 더블클릭.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
