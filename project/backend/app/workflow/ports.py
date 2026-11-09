"""Execution operations already used by the application, independent of LangGraph."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class WorkflowSnapshot:
    state: dict[str, Any] = field(default_factory=dict)
    pending: list[Any] = field(default_factory=list)
    runnable: bool = False
    checkpoint_id: str | None = None


class WorkflowExecution(Protocol):
    def inspect(self, thread_id: str) -> WorkflowSnapshot: ...
    def start(self, thread_id: str, state: dict) -> None: ...
    def resume(self, thread_id: str, value: Any) -> None: ...
    def continue_run(self, thread_id: str) -> None: ...
    def update(self, thread_id: str, state: dict, *, after_step: str) -> None: ...
