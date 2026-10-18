"""The interfaces a format plugs into."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pyarrow as pa

    from rexlib_metadata.result import ReadResult


class Reader(ABC):
    """Turns a file of one format into Arrow."""

    @abstractmethod
    def read_all(self, path: str) -> pa.Table:
        """Read every row of the file at `path` into one table."""

    @abstractmethod
    def read(self, path: str, **kwargs) -> ReadResult:
        """Return a lazy result over `path`, reading no row yet."""


class Convention(ABC):
    """Maps the columns of a file onto canonical ones."""

    @abstractmethod
    def matches(self, raw_schema: tuple[str, list[str]]) -> bool:
        """Say whether this convention applies to a raw table's schema."""

    @abstractmethod
    def apply(self, batch: pa.Table) -> pa.Table:
        """Return the table with its columns in canonical form."""

    @abstractmethod
    def to_file_name(self, canonical_name: str) -> str:
        """Return the name this convention writes a canonical column under."""

    @abstractmethod
    def to_canonical_name(self, file_name: str) -> str:
        """Return the canonical name of a column named as the file names it."""
