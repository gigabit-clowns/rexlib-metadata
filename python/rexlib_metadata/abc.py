"""The interfaces a format plugs into."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from rexlib_metadata.result import ReadResult

if TYPE_CHECKING:
    import pyarrow as pa


class Reader(ABC):
    """Turns a file of one format into Arrow."""

    @abstractmethod
    def read_all(self, path: str) -> pa.Table:
        """Read every row of the file at `path` into one table."""

    def read(self, path: str) -> ReadResult:
        """Return a lazy result over `path`, reading no row yet."""
        return ReadResult(path, self)

