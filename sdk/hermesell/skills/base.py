"""Abstract skill base — every sales skill implements this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SkillResult:
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @staticmethod
    def ok(**data: Any) -> SkillResult:
        return SkillResult(success=True, data=data)

    @staticmethod
    def fail(error: str) -> SkillResult:
        return SkillResult(success=False, error=error)


class SkillBase(ABC):
    name: str

    @abstractmethod
    async def execute(self, context: dict[str, Any], params: dict[str, Any]) -> SkillResult: ...
