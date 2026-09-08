"""Explicit, optional semantic retrieval over selected canonical artifacts."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmbeddingIdentity:
    model_id: str
    version: str
    digest: str
    dimensions: int
    implementation: str


class EmbeddingBackend(Protocol):
    @property
    def identity(self) -> EmbeddingIdentity: ...

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class SemanticRetriever(Protocol):
    def build(self, artifact_ids: Sequence[str], *, rebuild: bool = False) -> dict: ...

    def search(
        self,
        query: str,
        *,
        lexical_ids: Sequence[str] = (),
        graph_ids: Sequence[str] = (),
        limit: int = 10,
    ) -> dict: ...
