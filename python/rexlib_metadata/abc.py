# SPDX-License-Identifier: LGPL-2.1-or-later

"""The interfaces a format plugs into."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from rexlib_metadata.convention import RawTable

if TYPE_CHECKING:
    from collections.abc import Iterable, Set


class Reader(ABC):
    """Turns a file of one format into Arrow."""

    @abstractmethod
    def read_tables(self, path: str) -> list[RawTable]:
        """Read the file at `path` into one raw table per table it holds."""

    def read_tables_keeping(
        self, path: str, columns: Set[str]
    ) -> list[RawTable]:
        """Read the file at `path`, keeping only the columns `columns` names.

        `columns` is raw names, as the file spells them, and may name
        columns the file does not hold. Every table still comes back, with
        its rows, holding what it has of `columns`. This reads the whole
        file and drops the rest; a reader that can skip a column while
        parsing overrides it.
        """
        return [
            RawTable.of(
                table.schema.table_name,
                table.table.select(
                    [n for n in table.schema.column_names if n in columns]
                ),
            )
            for table in self.read_tables(path)
        ]


class Writer(ABC):
    """Turns Arrow back into a file of one format."""

    @abstractmethod
    def write_tables(self, path: str, tables: Iterable[RawTable]) -> None:
        """Write `tables` to `path`, one table of the file per raw table."""

