from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import Any, Callable


class ExportCancelled(RuntimeError):
    """Raised when a cooperative export cancellation is observed."""


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def throw_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise ExportCancelled("导出已取消")


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    current: int | None
    total: int | None
    percent: float | None
    message: str
    payload: dict[str, Any] = field(default_factory=dict)


ProgressCallback = Callable[[ProgressEvent], None]
