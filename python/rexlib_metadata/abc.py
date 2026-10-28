# SPDX-License-Identifier: LGPL-2.1-or-later

"""The interfaces a format plugs into."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from rexlib_metadata.convention import RawTable


class Reader(ABC):
    """Turns a file of one format into Arrow."""

    @abstractmethod
    def read_tables(self, path: str) -> list[RawTable]:
        """Read the file at `path` into one raw table per table it holds."""


class Writer(ABC):
    """Turns Arrow back into a file of one format."""

    @abstractmethod
    def write_tables(self, path: str, tables: Iterable[RawTable]) -> None:
        """Write `tables` to `path`, one table of the file per raw table."""

