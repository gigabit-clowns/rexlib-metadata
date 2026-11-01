# SPDX-License-Identifier: LGPL-2.1-or-later

"""The interfaces a format plugs into."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from rexlib_metadata.convention import RawSchema, RawTable

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Set

    import pyarrow as pa


class Reader(ABC):
    """Turns a file of one format into Arrow."""

    @abstractmethod
    def read_tables(self, path: str) -> list[RawTable]:
        """Read the file at `path` into one raw table per table it holds."""

    def read_schemas(self, path: str) -> list[RawSchema]:
        """Name every table of the file at `path` and its columns, in order.

        Which table fills which canonical one is decided from these alone,
        so that a chunked read chooses as a whole read does. This reads the
        whole file; a reader that can read its headers alone overrides it.
        """
        return [table.schema for table in self.read_tables(path)]

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

    def read_chunks(
        self, path: str, size: int, columns: Set[str] | None = None
    ) -> Iterator[tuple[int, RawTable]]:
        """Read the file at `path` `size` rows at a time.

        Each chunk comes with the ordinal of the table it belongs to, which
        is what tells two tables of one name apart. A table of no rows is
        one empty chunk. `columns` is raw names, as the file spells them, or
        None for all of them. This reads the whole file and slices it; a
        reader that can stream overrides it.
        """
        tables = (
            self.read_tables(path)
            if columns is None
            else self.read_tables_keeping(path, columns)
        )
        for ordinal, table in enumerate(tables):
            for piece in _sliced(table.table, size):
                yield ordinal, RawTable.of(table.schema.table_name, piece)


def _sliced(table: pa.Table, size: int) -> Iterator[pa.Table]:
    if not table.num_rows:
        yield table
        return
    for start in range(0, table.num_rows, size):
        yield table.slice(start, size)


class Writer(ABC):
    """Turns Arrow back into a file of one format."""

    @abstractmethod
    def write_tables(self, path: str, tables: Iterable[RawTable]) -> None:
        """Write `tables` to `path`, one table of the file per raw table."""

