# SPDX-License-Identifier: LGPL-2.1-or-later

"""The interfaces a format plugs into."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from rexlib_metadata.result import RawResult

if TYPE_CHECKING:
    from rexlib_metadata.convention import RawTable


class Reader(ABC):
    """Turns a file of one format into Arrow."""

    @abstractmethod
    def read_tables(self, path: str) -> list[RawTable]:
        """Read the file at `path` into one raw table per table it holds."""

    def read(self, path: str) -> RawResult:
        """Return a lazy result over the file's own tables, reading none."""
        return RawResult(path, self)

