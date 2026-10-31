# SPDX-License-Identifier: LGPL-2.1-or-later

"""Reading STAR files, and the conventions that come with them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rexlib_metadata._arrow import to_pyarrow_table, to_record_batch
from rexlib_metadata._rexlib import (
    _star_read_chunks,
    _star_read_tables,
    _star_write,
)
from rexlib_metadata.abc import Reader, Writer
from rexlib_metadata.convention import RawTable

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Set


class StarReader(Reader):
    """Reads a STAR file through the Rust parser."""

    def read_tables(self, path: str) -> list[RawTable]:
        """Read every data block of the file at `path`."""
        return [
            RawTable.of(name, to_pyarrow_table(batch))
            for name, batch in _star_read_tables(path)
        ]

    def read_tables_keeping(
        self, path: str, columns: Set[str]
    ) -> list[RawTable]:
        """Read every data block, the parser dropping what `columns` leaves."""
        return [
            RawTable.of(name, to_pyarrow_table(batch))
            for name, batch in _star_read_tables(path, set(columns))
        ]


    def read_chunks(
        self, path: str, size: int, columns: Set[str] | None = None
    ) -> Iterator[tuple[int, RawTable]]:
        """Read the blocks of `path` `size` rows at a time, as asked for."""
        chunks = _star_read_chunks(path, size, columns)
        try:
            for name, ordinal, batch in chunks:
                yield ordinal, RawTable.of(name, to_pyarrow_table(batch))
        finally:
            del chunks


class StarWriter(Writer):
    """Writes a STAR file through the Rust serializer."""

    def __init__(self, header: str | None = None) -> None:
        """Write `header`, comment lines only, before the first block."""
        self._header = header

    def write_tables(self, path: str, tables: Iterable[RawTable]) -> None:
        """Write one data block per table, in the order given."""
        _star_write(
            path,
            [
                (table.schema.table_name, to_record_batch(table.table))
                for table in tables
            ],
            self._header,
        )
