"""Provider contracts used by preparation nodes; implementations are injected."""

from typing import Protocol

from app.preparation.models import ExecutivePackage
from app.preparation.state import PreparationState


class DraftGenerator(Protocol):
    """Return a source-validated package using transcript and optional meeting_notes.

    Preserve their separate citation IDs and leave disagreements for manager review.
    """

    def __call__(self, state: PreparationState) -> ExecutivePackage: ...


class ReferenceSearch(Protocol):
    def __call__(self, query: str) -> list[dict]: ...
