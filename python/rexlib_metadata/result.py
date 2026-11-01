# SPDX-License-Identifier: LGPL-2.1-or-later

"""What a read hands back: the canonical view, and the file's own."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pyarrow as pa
import pyarrow.compute as pc

from rexlib_metadata._arrow import as_arrow_table
from rexlib_metadata.convention import RawTable, as_bundles
from rexlib_metadata.engine import (
    fills,
    produced_tables,
    read_canonical,
    source_columns,
    source_table,
    write_canonical,
    written_from,
)
from rexlib_metadata.join import joined_all
from rexlib_metadata.writing import folded, folds, replaced

if TYPE_CHECKING:
    from collections.abc import (
        Collection,
        Iterable,
        Iterator,
        Set,
    )

    import pandas as pd
    import polars as pl

    from rexlib_metadata.abc import Reader, Writer
    from rexlib_metadata.convention import ArrowColumn, ConventionBundle
    from rexlib_metadata.registry import MetadataRegistry
    from rexlib_metadata.schema import Relation, Schema, TableSchema

    Rows = Collection[int] | Collection[bool] | pa.Array | pa.ChunkedArray


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
        return _as_polars(self._one())

    def tables(self) -> tuple[RawTable, ...]:
        """Read the file, if it has not been read, and return every table."""
        if self._tables is None:
            self._tables = self.reread()
        return self._tables

    def reread(self) -> tuple[RawTable, ...]:
        """Read the file again and return every table, keeping none of them."""
        return tuple(self._reader.read_tables(self._path))

    def chunks(
        self, size: int, columns: Set[str] | None = None
    ) -> Iterator[tuple[int, RawTable]]:
        """Read the file `size` rows at a time, as its reader streams it."""
        _check_size(size)
        return self._reader.read_chunks(self._path, size, columns)

    def read_keeping(self, columns: Set[str]) -> tuple[RawTable, ...]:
        """Read the file again, keeping only the raw `columns` of it."""
        return tuple(self._reader.read_tables_keeping(self._path, columns))

    def write(self, path: str, *, writer: Writer | None = None) -> None:
        """Write the tables this result holds to `path`, as they are.

        The writer is chosen by the destination's extension unless `writer`
        names the one to use, and the names written are the ones the tables
        carry.
        """
        tables = self.tables()
        if writer is None:
            writer = self._registry.writer_for(path)
        replaced(path, lambda temporary: writer.write_tables(temporary, tables))

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


class Chunk:
    """Rows of one canonical table, already read."""

    def __init__(self, name: str, table: pa.Table) -> None:
        """Hold the rows under the canonical table name they belong to."""
        self._name = name
        self._table = table

    @property
    def name(self) -> str:
        """The canonical table these rows belong to."""
        return self._name

    def __len__(self) -> int:
        """How many rows this chunk holds."""
        return self._table.num_rows

    def to_arrow(self) -> pa.Table:
        """Return the rows as the Arrow table they already are."""
        return self._table

    def to_pandas(self) -> pd.DataFrame:
        """Return the rows as pandas."""
        return self._table.to_pandas()

    def to_polars(self) -> pl.DataFrame:
        """Return the rows as polars."""
        return _as_polars(self._table)


@dataclass(frozen=True)
class _Plan:
    source: tuple[RawTable, ...]
    bundles: tuple[ConventionBundle, ...]
    changed: dict[str, pa.Table | pd.DataFrame | pl.DataFrame]
    same_format: bool
    folds: dict[str, tuple[Relation, ...]]


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
        self._joined = False
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
        """Return a result over the one canonical table called `name`.

        The name is checked against the schema and nothing is read: a
        table the schema declares and this file does not fill is an error
        when the rows are asked for, which is the moment that knows.
        """
        if name not in self._schema:
            declared = ", ".join(repr(table.name) for table in self._schema)
            raise KeyError(
                f"No canonical table is called '{name}'; the ones there are "
                f"are {declared}"
            )
        return ReadResult(
            self._raw, self._bundles, self._schema, name, self._columns
        )

    def joined(self, name: str) -> ReadResult:
        """Return `result[name]` with the tables its rows point at joined in.

        Each row gains the columns of the row it points at, as
        `particles` gains the `optics` of its `optics_group`, in the order
        the file holds the rows. A related table this file does not fill
        joins nothing, and nothing is read until the rows are asked for.
        """
        view = self[name]
        view._joined = True
        return view

    def to_pandas(self) -> pd.DataFrame:
        """Read the file, if it has not been read, and return it as pandas."""
        return self._one().to_pandas()

    def to_polars(self) -> pl.DataFrame:
        """Read the file, if it has not been read, and return it as polars."""
        return _as_polars(self._one())

    def chunks(self, size: int) -> Iterator[Chunk]:
        """Read this result's canonical table `size` rows at a time.

        The file opens when iteration starts and closes when it ends, so a
        file larger than memory reads in bounded memory. A result that has
        not been narrowed to one canonical table raises: name the one you
        mean, as `result[name]`.
        """
        if self._table is None:
            raise ValueError(
                f"{self._raw.path} would be read a chunk at a time without "
                "saying which canonical table to read; name it, as "
                "result[name]"
            )
        _check_size(size)
        return self._chunks_of(self._schema[self._table], size)

    def _chunks_of(
        self, schema: TableSchema, size: int
    ) -> Iterator[Chunk]:
        related = self._related_whole(schema.name)
        stream = self._raw.chunks(size, self._raw_columns())
        ordinal, first = self._first_filling(stream, schema)
        yield self._chunk(schema, first, related)
        for at, raw in stream:
            if at != ordinal:
                return
            yield self._chunk(schema, raw, related)

    def _first_filling(
        self,
        stream: Iterator[tuple[int, RawTable]],
        schema: TableSchema,
    ) -> tuple[int, RawTable]:
        wanted = (
            (at, raw)
            for at, raw in stream
            if fills(raw, self._bundles, schema)
        )
        found = next(wanted, None)
        if found is None:
            raise ValueError(
                f"No convention fills canonical table '{schema.name}' from "
                f"{self._raw.path}; read the file's own columns through "
                ".raw, or pass bundle=, one bundle or several in priority order"
            )
        return found

    def _chunk(
        self,
        schema: TableSchema,
        raw: RawTable,
        related: tuple[tuple[Relation, pa.Table], ...],
    ) -> Chunk:
        table = self._filled([raw], schema)
        table = joined_all(table, related)
        return Chunk(schema.name, self._shown(table, schema.name))

    def _related_whole(
        self, name: str
    ) -> tuple[tuple[Relation, pa.Table], ...]:
        """Read whole, before a chunked read, the tables `name` points at."""
        if not self._joined:
            return ()
        wanted = {
            column.name
            for relation in self._schema.relations_of(name)
            for column in self._schema[relation.related].columns
        }
        raw_tables = self._raw.read_keeping(
            source_columns(wanted, self._bundles, self._schema)
        )
        return self._related(raw_tables, name)

    def _related(
        self, raw_tables: tuple[RawTable, ...], name: str
    ) -> tuple[tuple[Relation, pa.Table], ...]:
        filled = produced_tables(raw_tables, self._bundles, self._schema)
        return tuple(
            (relation, self._canonical(raw_tables, relation.related))
            for relation in self._schema.relations_of(name)
            if relation.related in filled
        )

    def _shown(self, table: pa.Table, name: str) -> pa.Table:
        if self._columns is None:
            return table
        tables = [name]
        if self._joined:
            tables += [r.related for r in self._schema.relations_of(name)]
        declared = {
            column.name for t in tables for column in self._schema[t].columns
        }
        return _projected(table, self._columns, name, declared)

    def _raw_columns(self) -> frozenset[str] | None:
        if self._columns is None:
            return None
        keys = (
            tuple(r.key for r in self._schema.relations_of(self._table))
            if self._joined and self._table is not None
            else ()
        )
        return source_columns(
            self._columns + keys, self._bundles, self._schema
        )

    def write(
        self,
        path: str,
        *,
        bundle: ConventionBundle | Iterable[ConventionBundle] | None = None,
        writer: Writer | None = None,
        updates: pa.Table | pd.DataFrame | pl.DataFrame | None = None,
        rows: Rows | None = None,
    ) -> None:
        """Write the whole file this result was read from to `path`.

        The source is read again, so that every canonical table and every
        column reaches the destination whatever this result shows, and the
        columns of `updates` take the place of their namesakes in the one
        canonical table this result shows.

        `rows` keeps only some rows of that table, in the order given:
        their positions, as `df.index` of a filtered frame, or a mask of
        one boolean per row. Every column of the rows kept is written, the
        ones no convention covers included, and the other tables whole.
        `updates` holds a row for every row written, in the same order:
        one per row of the table, or one per row `rows` keeps.

        The writer and the conventions come from the destination's
        extension, the way a read takes them from the source's, unless
        `writer` or `bundle` names the one to write through, `bundle` being
        one bundle or several in priority order. The source is
        read again by the reader it was read with. A column of the file
        that no convention writes, and a block no canonical table covers,
        are carried over untouched when the destination's writer is the
        source's, and left out when it is not. A column of `updates` that
        no write convention consumes raises, and so does a write that
        would hold nothing. The file is written beside the destination
        and moved over it at the end.
        """
        registry = self._raw.registry
        if writer is None:
            writer = registry.writer_for(path)
        bundles = as_bundles(bundle)
        if bundles is None:
            bundles = registry.bundles_for(path)
        same_format = _same_writer(writer, _writer_of(registry, self._raw.path))
        source, changed = self._source(updates, rows)
        tables = self._written(source, bundles, changed, same_format)
        if not tables:
            raise ValueError(
                f"Nothing of {self._raw.path} would reach {path}: no "
                "convention of the destination writes any of its tables"
            )
        replaced(path, lambda temporary: writer.write_tables(temporary, tables))

    def _written(
        self,
        source: tuple[RawTable, ...],
        bundles: tuple[ConventionBundle, ...],
        changed: dict[str, pa.Table | pd.DataFrame | pl.DataFrame],
        same_format: bool,
    ) -> list[RawTable]:
        names = produced_tables(source, self._bundles, self._schema)
        plan_folds = folds(names, bundles, self._schema)
        plan = _Plan(source, bundles, changed, same_format, plan_folds)
        filling = self._filling(source, names)
        skipped = folded(plan_folds)
        blocks = (
            self._block(raw, filling.get(id(raw)), plan)
            for raw in source
            if filling.get(id(raw)) not in skipped
        )
        return [block for block in blocks if block is not None]

    def _filling(
        self, source: tuple[RawTable, ...], names: tuple[str, ...]
    ) -> dict[int, str]:
        return {
            id(source_table(source, self._bundles, self._schema[name])): name
            for name in names
        }

    def _block(
        self, raw: RawTable, name: str | None, plan: _Plan
    ) -> RawTable | None:
        if name is None:
            return raw if plan.same_format else None
        updates = plan.changed.get(name)
        canonical = self._to_write(name, plan.source, updates, plan.folds)
        _check_written(canonical, updates, plan.bundles, self._schema[name])
        return RawTable.of(name, self._file_table(name, plan, canonical))

    def _source(
        self,
        updates: pa.Table | pd.DataFrame | pl.DataFrame | None,
        rows: Rows | None,
    ) -> tuple[
        tuple[RawTable, ...], dict[str, pa.Table | pd.DataFrame | pl.DataFrame]
    ]:
        source = self._raw.reread()
        if updates is None and rows is None:
            return source, {}
        shown = self._one_name(source)
        if rows is not None:
            source = self._selected(source, self._schema[shown], rows)
        if updates is None:
            return source, {}
        return source, {shown: self._own(source, shown, updates)}

    def _own(
        self,
        source: tuple[RawTable, ...],
        name: str,
        updates: pa.Table | pd.DataFrame | pl.DataFrame,
    ) -> pa.Table | pd.DataFrame | pl.DataFrame:
        if not self._joined:
            return updates
        frame = as_arrow_table(updates)
        own = [c for c in frame.column_names if c in self._schema[name]]
        current = joined_all(
            self._canonical(source, name), self._related(source, name)
        )
        _check_unchanged(frame, current, own, name)
        return frame.select(own)

    def _selected(
        self, source: tuple[RawTable, ...], table: TableSchema, rows: Rows
    ) -> tuple[RawTable, ...]:
        filling = source_table(source, self._bundles, table)
        if filling is None:
            return source
        positions = _positions(rows, filling.table.num_rows, table.name)
        kept = RawTable(filling.schema, filling.table.take(positions))
        return tuple(kept if raw is filling else raw for raw in source)

    def _file_table(
        self, name: str, plan: _Plan, canonical: pa.Table
    ) -> pa.Table:
        table = self._schema[name]
        columns = write_canonical(canonical, plan.bundles, table)
        if plan.same_format:
            columns.update(self._carried_over(plan.source, table, columns))
        return pa.table(list(columns.values()), names=list(columns))

    def _to_write(
        self,
        name: str,
        source: tuple[RawTable, ...],
        updates: pa.Table | pd.DataFrame | pl.DataFrame | None,
        folds: dict[str, tuple[Relation, ...]],
    ) -> pa.Table:
        """Return canonical table `name` as written: updated, folds joined."""
        schema = self._schema[name]
        table = _merged(self._canonical(source, name), updates, schema)
        related = tuple(
            (relation, self._canonical(source, relation.related))
            for relation in folds[name]
        )
        return joined_all(table, related)

    def _carried_over(
        self,
        raw_tables: tuple[RawTable, ...],
        table: TableSchema,
        written: dict[str, ArrowColumn],
    ) -> dict[str, ArrowColumn]:
        """Return the columns of the table the read drew on, minus `written`."""
        source = source_table(raw_tables, self._bundles, table)
        if source is None:
            return {}
        return {
            column: source.table.column(column)
            for column in source.table.column_names
            if column not in written
        }

    def _raw_tables(self) -> tuple[RawTable, ...]:
        columns = self._raw_columns()
        if columns is None:
            return self._raw.tables()
        return self._raw.read_keeping(columns)

    def _names(self, raw_tables: tuple[RawTable, ...]) -> tuple[str, ...]:
        filled = produced_tables(raw_tables, self._bundles, self._schema)
        if self._table is not None:
            return (self._table,) if self._table in filled else ()
        if self._columns is None:
            return filled
        return tuple(name for name in filled if self._shows(name))

    def _shows(self, name: str) -> bool:
        return any(
            column in self._schema[name] for column in self._columns or ()
        )

    def _canonical(
        self, raw_tables: tuple[RawTable, ...], name: str
    ) -> pa.Table:
        return self._filled(raw_tables, self._schema[name])

    def _filled(
        self, raw_tables: Iterable[RawTable], schema: TableSchema
    ) -> pa.Table:
        try:
            return read_canonical(raw_tables, self._bundles, schema)
        except pa.ArrowInvalid as error:
            raise ValueError(
                f"{self._raw.path}: canonical table '{schema.name}' holds a "
                f"value that does not parse: {error}"
            ) from error

    def _one(self) -> pa.Table:
        raw_tables = self._raw_tables()
        name = self._one_name(raw_tables)
        table = self._canonical(raw_tables, name)
        if self._joined:
            table = joined_all(table, self._related(raw_tables, name))
        return self._shown(table, name)

    def _one_name(self, raw_tables: tuple[RawTable, ...]) -> str:
        names = self._names(raw_tables)
        if len(names) == 1:
            return names[0]
        if not names:
            raise ValueError(
                f"No convention fills a canonical table from "
                f"{self._raw.path}; read the file's own columns through "
                ".raw, or pass bundle=, one bundle or several in priority order"
            )
        raise ValueError(
            f"{self._raw.path} fills {len(names)} canonical tables, "
            f"{', '.join(repr(n) for n in names)}; name the one you mean, "
            "as result[name]"
        )


def _as_polars(table: pa.Table) -> pl.DataFrame:
    import polars as pl  # noqa: PLC0415

    return cast("pl.DataFrame", pl.from_arrow(table))


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
    table: pa.Table, columns: tuple[str, ...], name: str, declared: Set[str]
) -> pa.Table:
    wanted = [column for column in columns if column in declared]
    absent = [column for column in wanted if column not in table.column_names]
    if absent:
        raise ValueError(
            f"Table '{name}' holds no "
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
    changed = as_arrow_table(updates)
    if changed.num_rows != canonical.num_rows:
        raise ValueError(
            f"updates holds {changed.num_rows} rows where {canonical.num_rows}"
            f" of table '{schema.name}' are written; it holds one per row "
            "written, in the same order: one per row of the table, or one "
            "per row rows= keeps"
        )
    for name in changed.column_names:
        column = changed.column(name).cast(schema.column(name).dtype)
        if name in canonical.column_names:
            index = canonical.column_names.index(name)
            canonical = canonical.set_column(index, name, column)
        else:
            canonical = canonical.append_column(name, column)
    return canonical


def _check_unchanged(
    frame: pa.Table, current: pa.Table, own: list[str], name: str
) -> None:
    changed = [
        column
        for column in frame.column_names
        if column not in own
        and not frame.column(column)
        .cast(current.column(column).type)
        .equals(current.column(column))
    ]
    if changed:
        raise ValueError(
            f"updates changes {', '.join(repr(c) for c in changed)}, which "
            f"table '{name}' does not hold but points at; write them through "
            "the table that holds them, as result[name].write(updates=...)"
        )


def _check_size(size: int) -> None:
    if size < 1:
        raise ValueError(f"A chunk has to hold at least one row, not {size}")


def _writer_of(registry: MetadataRegistry, path: str) -> Writer | None:
    try:
        return registry.writer_for(path)
    except ValueError:
        return None


def _same_writer(writer: Writer, other: Writer | None) -> bool:
    return writer is other or (
        type(writer) is type(other) and vars(writer) == vars(other)
    )


def _check_written(
    canonical: pa.Table,
    updates: pa.Table | pd.DataFrame | pl.DataFrame | None,
    bundles: tuple[ConventionBundle, ...],
    schema: TableSchema,
) -> None:
    if updates is None:
        return
    consumed = written_from(canonical.column_names, bundles, schema)
    given = as_arrow_table(updates).column_names
    lost = [name for name in given if name not in consumed]
    if lost:
        raise ValueError(
            f"updates holds {', '.join(repr(name) for name in lost)}, which "
            f"no convention writes from table '{schema.name}' as it stands, "
            "so the change would not reach the file"
        )


def _positions(rows: Rows, count: int, table: str) -> pa.Array:
    selection = _as_array(rows)
    if pa.types.is_boolean(selection.type):
        if len(selection) != count:
            raise ValueError(
                f"rows is a mask of {len(selection)} where table '{table}' "
                f"holds {count} rows"
            )
        return pc.indices_nonzero(selection.fill_null(False))
    if not pa.types.is_integer(selection.type):
        raise TypeError(
            f"rows holds {selection.type}; it takes row positions or a mask"
        )
    outside = pc.or_(
        pc.less(selection, pa.scalar(0)),
        pc.greater_equal(selection, pa.scalar(count)),
    )
    if selection.null_count or pc.any(outside).as_py():
        raise ValueError(
            f"rows names a row outside table '{table}', which holds {count}"
        )
    return selection.cast(pa.int64())


def _as_array(rows: Rows) -> pa.Array:
    to_arrow = getattr(rows, "to_arrow", None)
    found = rows if to_arrow is None else to_arrow()
    if isinstance(found, pa.ChunkedArray):
        return found.combine_chunks()
    if isinstance(found, pa.Array):
        return found
    return pa.array(found)
