"""The interfaces a format plugs into."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from rexlib_metadata.result import ReadResult

if TYPE_CHECKING:
    from rexlib_metadata.convention import RawTable


class Reader(ABC):
    """Turns a file of one format into Arrow."""

    @abstractmethod
    def read_tables(self, path: str) -> list[RawTable]:
        """Read the file at `path` into one raw table per table it holds."""

    def read(self, path: str) -> ReadResult:
        """Return a lazy result over `path`, reading no row yet."""
        return ReadResult(path, self)

