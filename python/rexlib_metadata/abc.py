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

