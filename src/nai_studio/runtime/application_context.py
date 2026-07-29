# -*- coding: utf-8 -*-
"""범주별 Operations 조립이 공유하는 최소 런타임 의존성 컨텍스트.

기존 조립 함수는 경로·설정·저장 함수·서비스를 ``globals()``에서 매번
꺼낸다. 이 모듈은 같은 네 종류를 이름으로 등록하고 호출 시점에 명시적으로
조회할 수 있게 한다. 실제 서비스 함수는 값으로, 현재 프로필처럼 바뀔 수
있는 경로와 설정은 provider로 등록해 둘을 구분한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping


PATHS = "paths"
SETTINGS = "settings"
STORAGE = "storage"
SERVICES = "services"
DEPENDENCY_GROUPS = (PATHS, SETTINGS, STORAGE, SERVICES)


class MissingBindingError(LookupError):
    """요청한 범주·그룹·이름이 등록되지 않았을 때 발생한다."""


class DuplicateBindingError(ValueError):
    """같은 의존성 이름을 조용히 덮어쓰려 할 때 발생한다."""


@dataclass(frozen=True)
class _Binding:
    value: Any
    dynamic: bool = False

    def resolve(self) -> Any:
        return self.value() if self.dynamic else self.value


def _binding_key(
    category: str,
    group: str,
    name: str,
) -> tuple[str, str, str]:
    category = str(category or "").strip()
    group = str(group or "").strip()
    name = str(name or "").strip()
    if not category:
        raise ValueError("의존성 범주 이름이 비어 있습니다.")
    if group not in DEPENDENCY_GROUPS:
        raise ValueError(f"알 수 없는 의존성 그룹입니다: {group}")
    if not name:
        raise ValueError("의존성 이름이 비어 있습니다.")
    return category, group, name


class WiringRegistry:
    """애플리케이션 시작 전에 범주별 의존성을 모으는 변경 가능한 조립기."""

    def __init__(self) -> None:
        self._bindings: dict[tuple[str, str, str], _Binding] = {}

    def bind_value(
        self,
        category: str,
        group: str,
        name: str,
        value: Any,
    ) -> "WiringRegistry":
        """함수 자체를 포함한 고정 값을 등록한다."""
        return self._bind(
            category,
            group,
            name,
            _Binding(value=value),
        )

    def bind_provider(
        self,
        category: str,
        group: str,
        name: str,
        provider: Callable[[], Any],
    ) -> "WiringRegistry":
        """프로필 경로·현재 설정처럼 조회할 때 평가할 값을 등록한다."""
        if not callable(provider):
            raise TypeError("provider는 인자 없는 callable이어야 합니다.")
        return self._bind(
            category,
            group,
            name,
            _Binding(value=provider, dynamic=True),
        )

    def _bind(
        self,
        category: str,
        group: str,
        name: str,
        binding: _Binding,
    ) -> "WiringRegistry":
        key = _binding_key(category, group, name)
        if key in self._bindings:
            raise DuplicateBindingError(
                "이미 등록된 의존성입니다: "
                f"{key[0]}.{key[1]}.{key[2]}"
            )
        self._bindings[key] = binding
        return self

    def freeze(self) -> "ApplicationContext":
        """등록 결과를 불변 컨텍스트로 고정한다."""
        return ApplicationContext(self._bindings)


class ApplicationContext:
    """범주와 책임 그룹을 거쳐 의존성을 명시적으로 조회한다."""

    def __init__(
        self,
        bindings: Mapping[
            tuple[str, str, str],
            _Binding,
        ] | None = None,
    ) -> None:
        copied = dict(bindings or {})
        for category, group, name in copied:
            _binding_key(category, group, name)
        self._bindings = MappingProxyType(copied)

    @classmethod
    def empty(cls) -> "ApplicationContext":
        return cls()

    def category(self, name: str) -> "CategoryWiring":
        category = str(name or "").strip()
        if not category:
            raise ValueError("의존성 범주 이름이 비어 있습니다.")
        return CategoryWiring(self, category)

    def require(
        self,
        category: str,
        group: str,
        name: str,
    ) -> Any:
        key = _binding_key(category, group, name)
        try:
            binding = self._bindings[key]
        except KeyError as error:
            raise MissingBindingError(
                "등록되지 않은 의존성입니다: "
                f"{key[0]}.{key[1]}.{key[2]}"
            ) from error
        return binding.resolve()

    def optional(
        self,
        category: str,
        group: str,
        name: str,
        default: Any = None,
    ) -> Any:
        key = _binding_key(category, group, name)
        binding = self._bindings.get(key)
        return default if binding is None else binding.resolve()

    def has(
        self,
        category: str,
        group: str,
        name: str,
    ) -> bool:
        return _binding_key(category, group, name) in self._bindings

    def describe(self) -> dict[str, dict[str, tuple[str, ...]]]:
        """토큰·경로 값은 노출하지 않고 등록된 이름만 진단용으로 돌려준다."""
        result: dict[str, dict[str, list[str]]] = {}
        for category, group, name in self._bindings:
            result.setdefault(category, {}).setdefault(group, []).append(
                name
            )
        return {
            category: {
                group: tuple(sorted(names))
                for group, names in sorted(groups.items())
            }
            for category, groups in sorted(result.items())
        }


@dataclass(frozen=True)
class CategoryWiring:
    """한 기능 범주 안에서 네 책임 그룹을 짧게 조회하는 view."""

    context: ApplicationContext
    category: str

    def path(self, name: str) -> Any:
        return self.context.require(self.category, PATHS, name)

    def setting(self, name: str) -> Any:
        return self.context.require(self.category, SETTINGS, name)

    def storage(self, name: str) -> Any:
        return self.context.require(self.category, STORAGE, name)

    def service(self, name: str) -> Any:
        return self.context.require(self.category, SERVICES, name)

    def optional(
        self,
        group: str,
        name: str,
        default: Any = None,
    ) -> Any:
        return self.context.optional(
            self.category,
            group,
            name,
            default,
        )


__all__ = [
    "ApplicationContext",
    "CategoryWiring",
    "DEPENDENCY_GROUPS",
    "DuplicateBindingError",
    "MissingBindingError",
    "PATHS",
    "SERVICES",
    "SETTINGS",
    "STORAGE",
    "WiringRegistry",
]
