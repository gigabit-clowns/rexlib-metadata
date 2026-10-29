# SPDX-License-Identifier: LGPL-2.1-or-later

"""What a read hands back: the canonical view, and the file's own."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pyarrow as pa

from rexlib_metadata.convention import RawTable
from rexlib_metadata.engine import (
    produced_tables,
    read_canonical,
    source_columns,
    source_table,
    write_canonical,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Set

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
            self._tables = self.reread()
        return self._tables

    def reread(self) -> tuple[RawTable, ...]:
        """Read the file again and return every table, keeping none of them."""
        return tuple(self._reader.read_tables(self._path))

    def read_keeping(self, columns: Set[str]) -> tuple[RawTable, ...]:
        """Read the file again, keeping only the raw `columns` of it."""
        return tuple(self._reader.read_tables_keeping(self._path, columns))

    def write(self, path: str) -> None:
        """Write the tables this result holds to `path`, as they are.

        The writer is chosen by the destination's extension, and the names
        written are the ones the tables carry.
        """
        tables = self.tables()
        writer = self._registry.writer_for(path)
        _replace(path, lambda temporary: writer.write_tables(temporary, tables))

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
        columns: Iterable[str] | None = None,
    ) -> None:
        """Hold the raw read, the bundles to apply and the schema to fill.

        `columns`, when given, is the canonical columns this result shows;
        a name no canonical table declares raises here, before any I/O.
        """
        self._raw = raw
        self._bundles = tuple(bundles)
        self._schema = schema
        self._table = table
        self._columns = None if columns is None else tuple(columns)
        _check_declared(self._columns, schema)

    @property
    def raw(self) -> RawResult:
        """The same file, read as it names its own tables and columns."""
        return self._raw

    @property
    def names(self) -> tuple[str, ...]:
        """Name the canonical tables this result shows from this file."""
        return self._names(self._raw_tables())

    def __getitem__(self, name: str) -> ReadResult:
        """Return a result over the one canonical table called `name`."""
        names = self.names
        if name not in names:
            raise KeyError(
                f"{self._raw.path} fills no canonical table '{name}'; it "
                f"fills {', '.join(repr(n) for n in names)}"
            )
        return ReadResult(
            self._raw, self._bundles, self._schema, name, self._columns
        )

    def to_pandas(self) -> pd.DataFrame:
        """Read the file, if it has not been read, and return it as pandas."""
        return self._one().to_pandas()

    def to_polars(self) -> pl.DataFrame:
        """Read the file, if it has not been read, and return it as polars."""
        import polars as pl  # noqa: PLC0415

        return cast("pl.DataFrame", pl.from_arrow(self._one()))

    def write(
        self,
        path: str,
        *,
        bundle: ConventionBundle | None = None,
        updates: pa.Table | pd.DataFrame | pl.DataFrame | None = None,
    ) -> None:
        """Write the whole file this result was read from to `path`.

        The source is read again, so that every canonical table and every
        column reaches the destination whatever this result shows, and the
        columns of `updates` take the place of their namesakes in the one
        canonical table this result shows. `updates` holds a row for every
        row of that table, in the same order.

        The conventions come from the destination's extension, the way a
        read takes them from the source's, unless `bundle` names the one to
        write through. A column of the file that no convention writes is
        carried over untouched when the destination is the format the
        result was read from, and left out when it is not. The file is
        written beside the destination and moved over it at the end.
        """
        registry = self._raw.registry
        writer = registry.writer_for(path)
        bundles = (
            (bundle,) if bundle is not None else registry.bundles_for(path)
        )
        source = self._raw.reread()
        changed = {} if updates is None else {self._one_name(source): updates}
        tables = [
            RawTable.of(
                name,
                self._file_table(
                    name, source, bundles, path, changed.get(name)
                ),
            )
            for name in produced_tables(source, self._bundles, self._schema)
        ]
        _replace(path, lambda temporary: writer.write_tables(temporary, tables))

    def _file_table(
        self,
        name: str,
        source: tuple[RawTable, ...],
        bundles: tuple[ConventionBundle, ...],
        path: str,
        updates: pa.Table | pd.DataFrame | pl.DataFrame | None,
    ) -> pa.Table:
        table = self._schema[name]
        canonical = _merged(self._canonical(source, name), updates, table)
        columns = write_canonical(canonical, bundles, table)
        columns.update(self._carried_over(source, table, columns, path))
        return pa.table(list(columns.values()), names=list(columns))

    def _carried_over(
        self,
        raw_tables: tuple[RawTable, ...],
        table: TableSchema,
        written: dict[str, ArrowColumn],
        path: str,
    ) -> dict[str, ArrowColumn]:
        """Return the columns of the table the read drew on, minus `written`."""
        if Path(path).suffix.lower() != Path(self._raw.path).suffix.lower():
            return {}
        source = source_table(raw_tables, self._bundles, table)
        if source is None:
            return {}
        return {
            column: source.table.column(column)
            for column in source.table.column_names
            if column not in written
        }

    def _raw_tables(self) -> tuple[RawTable, ...]:
        if self._columns is None:
            return self._raw.tables()
        return self._raw.read_keeping(
            source_columns(self._columns, self._bundles, self._schema)
        )

    def _names(self, raw_tables: tuple[RawTable, ...]) -> tuple[str, ...]:
        if self._table is not None:
            return (self._table,)
        filled = produced_tables(raw_tables, self._bundles, self._schema)
        if self._columns is None:
            return filled
        return tuple(
            name
            for name in filled
            if any(column in self._schema[name] for column in self._columns)
        )

    def _canonical(
        self, raw_tables: tuple[RawTable, ...], name: str
    ) -> pa.Table:
        return read_canonical(raw_tables, self._bundles, self._schema[name])

    def _one(self) -> pa.Table:
        raw_tables = self._raw_tables()
        name = self._one_name(raw_tables)
        table = self._canonical(raw_tables, name)
        if self._columns is None:
            return table
        return _projected(table, self._columns, self._schema[name])

    def _one_name(self, raw_tables: tuple[RawTable, ...]) -> str:
        names = self._names(raw_tables)
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


def _check_declared(columns: tuple[str, ...] | None, schema: Schema) -> None:
    unknown = [
        name
        for name in columns or ()
        if not any(name in table for table in schema)
    ]
    if unknown:
        raise ValueError(
            f"No canonical table declares "
            f"{', '.join(repr(name) for name in unknown)}"
        )


def _projected(
    table: pa.Table, columns: tuple[str, ...], schema: TableSchema
) -> pa.Table:
    wanted = [name for name in columns if name in schema]
    absent = [name for name in wanted if name not in table.column_names]
    if absent:
        raise ValueError(
            f"Table '{schema.name}' holds no "
            f"{', '.join(repr(name) for name in absent)} in this file"
        )
    return table.select(wanted)


def _merged(
    canonical: pa.Table,
    updates: pa.Table | pd.DataFrame | pl.DataFrame | None,
    schema: TableSchema,
) -> pa.Table:
    """Return `canonical` with the columns of `updates` in place of its own."""
    if updates is None:
        return canonical
    changed = _as_arrow(updates)
    if changed.num_rows != canonical.num_rows:
        raise ValueError(
            f"updates holds {changed.num_rows} rows where table "
            f"'{schema.name}' holds {canonical.num_rows}; a row written back "
            "has to be the row read, so a filtered frame makes every column "
            "yours: write it through a result of its own"
        )
    for name in changed.column_names:
        column = changed.column(name).cast(schema.column(name).dtype)
        if name in canonical.column_names:
            index = canonical.column_names.index(name)
            canonical = canonical.set_column(index, name, column)
        else:
            canonical = canonical.append_column(name, column)
    return canonical


def _as_arrow(frame: pa.Table | pd.DataFrame | pl.DataFrame) -> pa.Table:
    if isinstance(frame, pa.Table):
        return frame
    to_arrow = getattr(frame, "to_arrow", None)
    if to_arrow is not None:
        return cast("pa.Table", to_arrow())
    return pa.Table.from_pandas(
        cast("pd.DataFrame", frame), preserve_index=False
    )


def _replace(path: str, write: Callable[[str], None]) -> None:
    """Write through a file beside `path`, moved over it once written."""
    destination = Path(path)
    descriptor, temporary = tempfile.mkstemp(
        dir=destination.parent, suffix=destination.suffix
    )
    os.close(descriptor)
    try:
        write(temporary)
        Path(temporary).replace(destination)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
