# SPDX-License-Identifier: LGPL-2.1-or-later

"""What a read hands back: the canonical view, and the file's own."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

import pyarrow as pa

from rexlib_metadata.convention import RawTable
from rexlib_metadata.engine import (
    produced_tables,
    read_canonical,
    source_table,
    write_canonical,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    import pandas as pd
    import polars as pl

    from rexlib_metadata.abc import Reader
    from rexlib_metadata.convention import ArrowColumn, ConventionBundle
    from rexlib_metadata.registry import MetadataRegistry
    from rexlib_metadata.schema import Schema, TableSchema


class RawResult:
    """A file waiting to be read, and its own tables once it has been."""

    def __init__(
        self, path: str, reader: Reader, registry: MetadataRegistry
    ) -> None:
        """Hold `path` and the `reader` that will read it, opening nothing."""
        self._path = path
        self._reader = reader
        self._registry = registry
        self._tables: tuple[RawTable, ...] | None = None

    @property
    def path(self) -> str:
        """The file this result reads."""
        return self._path

    @property
    def registry(self) -> MetadataRegistry:
        """The registry that answers for this file's format."""
        return self._registry

    @property
    def names(self) -> tuple[str, ...]:
        """Read the file, if it has not been read, and name its tables."""
        return tuple(table.schema.table_name for table in self.tables())

    def __getitem__(self, name: str) -> RawResult:
        """Return a result over the one table the file calls `name`."""
        for table in self.tables():
            if table.schema.table_name == name:
                return self._holding((table,))
        raise KeyError(
            f"{self._path} holds no table '{name}'; it holds "
            f"{', '.join(repr(n) for n in self.names)}"
        )

    def to_pandas(self) -> pd.DataFrame:
        """Read the file, if it has not been read, and return it as pandas."""
        return self._one().to_pandas()

    def to_polars(self) -> pl.DataFrame:
        """Read the file, if it has not been read, and return it as polars."""
        import polars as pl  # noqa: PLC0415

        return cast("pl.DataFrame", pl.from_arrow(self._one()))

    def tables(self) -> tuple[RawTable, ...]:
        """Read the file, if it has not been read, and return every table."""
        if self._tables is None:
            self._tables = tuple(self._reader.read_tables(self._path))
        return self._tables

    def write(self, path: str) -> None:
        """Write the tables this result holds to `path`, as they are.

        The writer is chosen by the destination's extension, and the names
        written are the ones the tables carry.
        """
        self._registry.writer_for(path).write_tables(path, self.tables())

    def _one(self) -> pa.Table:
        tables = self.tables()
        if len(tables) != 1:
            raise ValueError(
                f"{self._path} holds {len(tables)} tables, "
                f"{', '.join(repr(n) for n in self.names)}; name the one you "
                "mean, as result[name]"
            )
        return tables[0].table

    def _holding(self, tables: tuple[RawTable, ...]) -> RawResult:
        result = RawResult(self._path, self._reader, self._registry)
        result._tables = tables
        return result


class ReadResult:
    """A file as the canonical vocabulary names it, not as it names itself."""

    def __init__(
        self,
        raw: RawResult,
        bundles: Iterable[ConventionBundle],
        schema: Schema,
        table: str | None = None,
    ) -> None:
        """Hold the raw read, the bundles to apply and the schema to fill."""
        self._raw = raw
        self._bundles = tuple(bundles)
        self._schema = schema
        self._table = table

    @property
    def raw(self) -> RawResult:
        """The same file, read as it names its own tables and columns."""
        return self._raw

    @property
    def names(self) -> tuple[str, ...]:
        """Name the canonical tables these conventions fill from this file."""
        if self._table is not None:
            return (self._table,)
        return produced_tables(self._raw.tables(), self._bundles, self._schema)

    def __getitem__(self, name: str) -> ReadResult:
        """Return a result over the one canonical table called `name`."""
        if name not in self.names:
            raise KeyError(
                f"{self._raw.path} fills no canonical table '{name}'; it "
                f"fills {', '.join(repr(n) for n in self.names)}"
            )
        return ReadResult(self._raw, self._bundles, self._schema, name)

    def to_pandas(self) -> pd.DataFrame:
        """Read the file, if it has not been read, and return it as pandas."""
        return self._one().to_pandas()

    def to_polars(self) -> pl.DataFrame:
        """Read the file, if it has not been read, and return it as polars."""
        import polars as pl  # noqa: PLC0415

        return cast("pl.DataFrame", pl.from_arrow(self._one()))

    def write(
        self, path: str, *, bundle: ConventionBundle | None = None
    ) -> None:
        """Write every canonical table this result fills to `path`.

        The conventions come from the destination's extension, the way a
        read takes them from the source's, unless `bundle` names the one to
        write through. A column of the file that no convention writes is
        carried over untouched when the destination is the format the
        result was read from, and left out when it is not.
        """
        registry = self._raw.registry
        writer = registry.writer_for(path)
        bundles = (
            (bundle,) if bundle is not None else registry.bundles_for(path)
        )
        tables = [
            RawTable.of(name, self._file_table(name, bundles, path))
            for name in self.names
        ]
        writer.write_tables(path, tables)

    def _file_table(
        self, name: str, bundles: tuple[ConventionBundle, ...], path: str
    ) -> pa.Table:
        table = self._schema[name]
        columns = write_canonical(self._canonical(name), bundles, table)
        columns.update(self._carried_over(table, bundles, columns, path))
        return pa.table(list(columns.values()), names=list(columns))

    def _carried_over(
        self,
        table: TableSchema,
        bundles: tuple[ConventionBundle, ...],
        written: dict[str, ArrowColumn],
        path: str,
    ) -> dict[str, ArrowColumn]:
        if Path(path).suffix.lower() != Path(self._raw.path).suffix.lower():
            return {}
        source = source_table(self._raw.tables(), self._bundles, table)
        if source is None:
            return {}
        return {
            column: source.table.column(column)
            for column in source.table.column_names
            if column not in written
        }

    def _canonical(self, name: str) -> pa.Table:
        return read_canonical(
            self._raw.tables(), self._bundles, self._schema[name]
        )

    def _one(self) -> pa.Table:
        name = self._table if self._table is not None else self._sole_name()
        return self._canonical(name)

    def _sole_name(self) -> str:
        names = self.names
        if len(names) == 1:
            return names[0]
        if not names:
            raise ValueError(
                f"No convention fills a canonical table from "
                f"{self._raw.path}; read the file's own columns through "
                ".raw, or pass a bundle of your own as bundle="
            )
        raise ValueError(
            f"{self._raw.path} fills {len(names)} canonical tables, "
            f"{', '.join(repr(n) for n in names)}; name the one you mean, "
            "as result[name]"
        )
