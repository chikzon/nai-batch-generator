"""캐릭터 위치 방식의 공통 계약.

NovelAI가 실제로 받는 값은 ``use_coords``와 인물별 ``center``지만, 사용자가
고르는 방식은 세 가지다.

``ai``
    AI's Choice. 저장된 수동 좌표는 보존하되 이번 요청에는 적용하지 않는다.
``grid``
    5×5 위치판. 칸 중심값도 결국 연속 좌표와 같은 payload로 보낸다.
``coordinate``
    0~1 연속 좌표를 그대로 보낸다.

구형 설정에는 ``position_mode``가 없으므로 ``use_coords``만 읽어 호환한다.
이 함수들은 파생값만 만들며 기존 설정을 변환하거나 저장하지 않는다.
"""

import math


POSITION_MODES = frozenset(("ai", "grid", "coordinate"))
POSITION_GRID = (0.1, 0.3, 0.5, 0.7, 0.9)


def normalize_position_mode(value=None, use_coords=False):
    """알려진 모드 또는 구형 ``use_coords``에서 안전한 파생 모드를 돌려준다."""
    mode = str(value or "").strip().lower()
    if mode in POSITION_MODES:
        return mode
    return "coordinate" if bool(use_coords) else "ai"


def position_mode_uses_coords(value=None, use_coords=False):
    """해당 모드가 NAI 좌표 전송을 사용하는지 돌려준다."""
    return normalize_position_mode(value, use_coords) != "ai"


def position_mode_label(value=None, use_coords=False):
    """사용자에게 표시할 짧은 한국어 이름."""
    return {
        "ai": "AI 자동",
        "grid": "위치판",
        "coordinate": "좌표",
    }[normalize_position_mode(value, use_coords)]


def with_centers(config, centers):
    """실행 설정 사본에 이번 요청의 캐릭터 좌표만 얹는다."""
    result = dict(config or {})
    result["char_centers"] = centers
    return result


def with_position_mode(config, mode=None, use_positions=False):
    """실행 설정 사본에 위치 방식을 적용하고 저장 원본은 건드리지 않는다."""
    result = dict(config or {})
    normalized = str(mode or "").strip().lower()
    if normalized in POSITION_MODES:
        result["position_mode"] = normalized
        result["use_coords"] = normalized != "ai"
    elif use_positions:
        result["position_mode"] = "coordinate"
        result["use_coords"] = True
    return result


def spread_centers(count):
    """NAI 좌표 격자 안에서 최대 두 줄로 겹치지 않게 인물을 벌린다."""
    if count <= 1:
        return [{"x": 0.5, "y": 0.5}]
    if count == 2:
        return [{"x": 0.3, "y": 0.5}, {"x": 0.7, "y": 0.5}]
    rows = 1 if count <= 5 else 2
    per_row = -(-count // rows)
    ys = [0.5] if rows == 1 else [0.3, 0.7]

    def pick(index, total):
        if total == 1:
            return POSITION_GRID[2]
        step = 4 / (total - 1)
        return POSITION_GRID[min(4, round(index * step))]

    centers = []
    for index in range(count):
        row = index // per_row
        column = index % per_row
        row_count = min(per_row, count - row * per_row)
        centers.append({
            "x": pick(column, row_count),
            "y": ys[min(row, len(ys) - 1)],
        })
    return centers


def normalize_scene_centers(value, *, limit=6):
    """저장·전송할 0..1 캐릭터 좌표 목록을 전부 검증한다."""
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("캐릭터 위치는 목록이어야 합니다.")
    centers = []
    for index, center in enumerate(value[:limit]):
        if not isinstance(center, dict):
            raise ValueError(f"{index + 1}번 캐릭터 위치 형식이 잘못되었습니다.")
        try:
            x = float(center["x"])
            y = float(center["y"])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError(
                f"{index + 1}번 캐릭터 위치는 x/y 숫자가 필요합니다."
            )
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError(f"{index + 1}번 캐릭터 위치는 유한한 숫자여야 합니다.")
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError(f"{index + 1}번 캐릭터 위치는 0~1 범위여야 합니다.")
        centers.append({"x": round(x, 4), "y": round(y, 4)})
    return centers
