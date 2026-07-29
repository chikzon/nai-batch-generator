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

POSITION_MODES = frozenset(("ai", "grid", "coordinate"))


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
