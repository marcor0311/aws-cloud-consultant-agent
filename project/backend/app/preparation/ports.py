"""Provider contracts used by preparation nodes; implementations are injected."""

from typing import Protocol

from app.preparation.models import ExecutivePackage
from app.preparation.state import PreparationState


class DraftGenerator(Protocol):
    def __call__(self, state: PreparationState) -> ExecutivePackage: ...


class ReferenceSearch(Protocol):
    def __call__(self, query: str) -> list[dict]: ...
