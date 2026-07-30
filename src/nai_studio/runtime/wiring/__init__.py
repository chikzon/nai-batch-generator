# -*- coding: utf-8 -*-
"""기능별 Operations 조립 전용 계층 (레거시 축소 단계 3).

여기는 기존 service dataclass를 만들기만 한다 — 기능 알고리즘·경로 상수·
상태를 새로 정의하지 않는다. 모든 의존성은 호출자가 넘긴 `app` 네임스페이스
(레거시 호환면의 globals())에서 호출 시점에 찾는다. 그래서 기존
`patch.object(APP, …)` monkeypatch 계약이 그대로 산다.
"""
