# SPDX-License-Identifier: LGPL-2.1-or-later

"""What a read hands back: the canonical view, and the file's own."""

from __future__ import annotations

from itertools import takewhile
from typing import TYPE_CHECKING

import pyarrow as pa

from rexlib_metadata._arrow import as_arrow_table, to_pandas
from rexlib_metadata.convention import RawSchema, RawTable, as_bundles
from rexlib_metadata.editing import (
    Edit,
    as_mask,
    as_positions,
    merged,
    own_updates,
    positions,
    shown,
    streamed,
)
from rexlib_metadata.engine import produced_tables, source_columns
from rexlib_metadata.join import joined_all
from rexlib_metadata.reading import Reading, block_chunks, narrowed_all
from rexlib_metadata.rewrite import Rewrite
from rexlib_metadata.writing import replaced, typed

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence, Set

    import pandas as pd
    import polars as pl

    from rexlib_metadata._arrow import Frame
    from rexlib_metadata.abc import Reader, Writer
    from rexlib_metadata.convention import ConventionBundle
    from rexlib_metadata.editing import Mask, Positions, Rows
    from rexlib_metadata.registry import MetadataRegistry
    from rexlib_metadata.schema import Relation, Schema, TableSchema


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
        self._ordinal: int | None = None

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
        """Return a result over the one table the file calls `name`.

        Every read through it reads that table alone.
        """
        for at, table in enumerate(self.tables()):
            if table.schema.table_name == name:
                ordinal = at if self._ordinal is None else self._ordinal
                return self._holding((table,), ordinal)
        raise KeyError(
            f"{self._path} holds no table '{name}'; it holds "
            f"{', '.join(repr(n) for n in self.names)}"
        )

    def to_arrow(self) -> pa.Table:
        """Read the file, if it has not been read, and return it as Arrow."""
        return self._one()

    def to_pandas(self) -> pd.DataFrame:
        """Read the file, if it has not been read, and return it as pandas."""
        return to_pandas(self._one())

    def to_polars(self) -> pl.DataFrame:
        """Read the file, if it has not been read, and return it as polars."""
        return _as_polars(self._one())

    def tables(self) -> tuple[RawTable, ...]:
        """Read the file, if it has not been read, and return every table."""
        if self._tables is None:
            self._tables = self._reread()
        return self._tables

    def _reread(self) -> tuple[RawTable, ...]:
        """Read the file again and return every table, keeping none of them."""
        return self._own(self._reader.read_tables(self._path))

    def _chunks(
        self, size: int, columns: Set[str] | None = None
    ) -> Iterator[tuple[int, RawTable]]:
        """Read the file `size` rows at a time, as its reader streams it."""
        _check_size(size)
        chunks = self._reader.read_chunks(self._path, size, columns)
        if self._ordinal is None:
            return chunks
        mine = self._ordinal
        before = takewhile(lambda chunk: chunk[0] <= mine, chunks)
        return ((0, raw) for at, raw in before if at == mine)

    def _schemas(
        self, columns: Set[str] | None = None
    ) -> tuple[RawSchema, ...]:
        """Name every table and what it has of `columns`, reading no row."""
        if self._tables is None:
            found = self._reader.read_schemas(self._path)
        else:
            found = [table.schema for table in self._tables]
        return narrowed_all(tuple(found), columns)

    def _read_keeping(self, columns: Set[str]) -> tuple[RawTable, ...]:
        """Read the file again, keeping only the raw `columns` of it."""
        return self._own(self._reader.read_tables_keeping(self._path, columns))

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

    def _own(self, tables: Iterable[RawTable]) -> tuple[RawTable, ...]:
        every = tuple(tables)
        return every if self._ordinal is None else (every[self._ordinal],)

    def _holding(
        self, tables: tuple[RawTable, ...], ordinal: int
    ) -> RawResult:
        result = RawResult(self._path, self._reader, self._registry)
        result._tables = tables
        result._ordinal = ordinal
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
        return to_pandas(self._table)

    def to_polars(self) -> pl.DataFrame:
        """Return the rows as polars."""
        return _as_polars(self._table)


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
        self._rows: pa.Array | None = None
        self._updates: Frame | None = None
        self._source = Reading(raw, self._bundles, schema)
        _check_declared(self._columns, schema)

    @property
    def raw(self) -> RawResult:
        """The same file, read as it names its own tables and columns."""
        return self._raw

    @property
    def names(self) -> tuple[str, ...]:
        """Name the canonical tables this result shows from this file."""
        return self._names(self._raw._schemas())

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

    def take(self, positions: Rows) -> ReadResult:
        """Return this view keeping only the rows at `positions`, in order.

        `positions` count from zero, as `df.index` of a filtered frame, and
        may come in any order. Nothing is read until the rows are asked for;
        a position outside the table raises then.
        """
        return self._selecting(as_positions(positions))

    def where(self, mask: Rows) -> ReadResult:
        """Return this view keeping only the rows where `mask` is true.

        `mask` holds one boolean per row of the table, a null keeping
        nothing. Nothing is read until the rows are asked for.
        """
        return self._selecting(as_mask(mask))

    def updated(self, updates: Frame) -> ReadResult:
        """Return this view with the columns of `updates` in their place.

        `updates`, pandas, polars or Arrow, holds one row per row the view
        shows, in the same order: after `take` or `where`, one per row
        kept. Each column takes the place of its namesake in the table
        shown, or joins it; a column of a table joined in may only hold
        what it holds already. A write carries every other column.
        """
        if self._updates is not None:
            raise ValueError(
                "A view is updated once: give every column to one "
                "updated()"
            )
        view = self._copy()
        view._updates = updates
        return view

    def to_arrow(self) -> pa.Table:
        """Read the file, if it has not been read, and return it as Arrow."""
        return self._one()

    def to_pandas(self) -> pd.DataFrame:
        """Read the file, if it has not been read, and return it as pandas."""
        return to_pandas(self._one())

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
        name = schema.name
        pointed_at = bool(self._schema.related_to(name))
        kept = None
        if self._rows is not None and not pointed_at:
            kept = streamed(self._rows, name)
        if self._rows is not None and kept is None:
            yield from _sliced(name, self._one(), size)
            return
        found = self._raw._schemas()
        related = self._related_whole(name, found)
        edit = self._edit(name, kept)
        for table in self._canonical_chunks(schema, found, size, pointed_at):
            yield self._chunk(schema, table, related, edit)
        if edit is not None:
            edit.check()

    def _canonical_chunks(
        self,
        schema: TableSchema,
        found: tuple[RawSchema, ...],
        size: int,
        pointed_at: bool,
    ) -> Iterator[pa.Table]:
        columns = self._raw_columns()
        raw = narrowed_all(found, columns)
        ordinal = self._ordinal_of(schema, found)
        source = self._source
        if pointed_at:
            whole = source.built(schema.name, raw[ordinal], ordinal, columns)
            for start in range(0, max(whole.num_rows, 1), size):
                yield whole.slice(start, size)
            return
        bound = source.bound(schema.name, raw[ordinal], ordinal)
        for piece in block_chunks(self._raw, size, ordinal, columns):
            yield source.filled([piece], schema.name, bound)

    def _ordinal_of(
        self, schema: TableSchema, raw: tuple[RawSchema, ...]
    ) -> int:
        ordinal = self._source.assigned(raw).get(schema.name)
        if ordinal is None:
            raise _unfilled(f"canonical table '{schema.name}'", self._raw.path)
        return ordinal

    def _chunk(
        self,
        schema: TableSchema,
        table: pa.Table,
        related: tuple[tuple[Relation, pa.Table], ...],
        edit: Edit | None,
    ) -> Chunk:
        if edit is not None:
            table = edit.rows_of(table)
        table = joined_all(table, related)
        if edit is not None:
            table = self._updated(table, edit)
        return Chunk(schema.name, self._shown(table, schema.name))

    def _related_whole(
        self, name: str, found: tuple[RawSchema, ...]
    ) -> tuple[tuple[Relation, pa.Table], ...]:
        """Read whole, before a chunked read, the tables `name` points at."""
        if not self._joined:
            return ()
        wanted = {
            column.name
            for relation in self._schema.relations_of(name)
            for column in self._schema[relation.related].columns
        }
        columns = source_columns(wanted, self._bundles, self._schema)
        raw = narrowed_all(found, columns)
        chosen = self._source.assigned(found)
        return tuple(
            (
                relation,
                self._source.built(
                    relation.related,
                    raw[chosen[relation.related]],
                    chosen[relation.related],
                    columns,
                ),
            )
            for relation in self._schema.relations_of(name)
            if relation.related in chosen
        )

    def _related(
        self,
        raw_tables: tuple[RawTable, ...],
        name: str,
        chosen: dict[str, int],
    ) -> tuple[tuple[Relation, pa.Table], ...]:
        return tuple(
            (
                relation,
                self._source.filled(
                    (raw_tables[chosen[relation.related]],), relation.related
                ),
            )
            for relation in self._schema.relations_of(name)
            if relation.related in chosen
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
    ) -> None:
        """Write the whole file this result was read from to `path`.

        The source is read again, so that every canonical table and every
        column reaches the destination whatever this result shows, the one
        table it shows as `take`, `where` and `updated` left it: only the
        rows kept, every column of them, the ones no convention covers
        included, and the other tables whole. It is read and written a
        chunk at a time, the tables others point at read whole first,
        unless a table others do not point at shares its raw table or
        `take` holds positions out of order.

        The writer and the conventions come from the destination's
        extension, the way a read takes them from the source's, unless
        `writer` or `bundle` names the one to write through, `bundle` being
        one bundle or several in priority order. The source is
        read again by the reader it was read with. A column of the file
        that no convention writes, and a block no canonical table covers,
        are carried over untouched when the destination's writer is the
        source's, and left out when it is not. A column `updated` gave that
        no write convention consumes raises, and so does a write that would
        hold nothing. The file is written beside the destination
        and moved over it at the end.
        """
        registry = self._raw.registry
        if writer is None:
            writer = registry.writer_for(path)
        bundles = as_bundles(bundle)
        if bundles is None:
            bundles = registry.bundles_for(path)
        name = None
        if self._rows is not None or self._updates is not None:
            name = self._one_name(self._raw._schemas())
        rewrite = Rewrite(self._source, self._joined, writer, bundles)
        rewrite.write(path, name, self._updates, self._rows)

    def _selecting(self, rows: pa.Array) -> ReadResult:
        if self._rows is not None or self._updates is not None:
            raise ValueError(
                "Rows are kept once, and before updated(): give them to one "
                "take() or where()"
            )
        view = self._copy()
        view._rows = rows
        return view

    def _copy(self) -> ReadResult:
        view = ReadResult(
            self._raw, self._bundles, self._schema, self._table, self._columns
        )
        view._joined = self._joined
        view._rows = self._rows
        view._updates = self._updates
        return view

    def _edit(
        self, name: str, kept: Mask | Positions | None = None
    ) -> Edit | None:
        if self._rows is None and self._updates is None:
            return None
        frame = None
        if self._updates is not None:
            tables = shown(self._schema, name, self._joined)
            frame = typed(as_arrow_table(self._updates), tables, "updates")
        return Edit(name, frame, kept)

    def _edited(self, table: pa.Table, name: str) -> pa.Table:
        edit = self._edit(name)
        if edit is None:
            return table
        if self._rows is not None:
            table = table.take(positions(self._rows, table.num_rows, name))
        table = self._updated(table, edit)
        edit.check()
        return table

    def _updated(self, table: pa.Table, edit: Edit) -> pa.Table:
        frame = edit.updates_of(table.num_rows)
        if frame is None:
            return table
        return merged(table, own_updates(frame, table, self._schema, edit.name))

    def _raw_tables(self) -> tuple[RawTable, ...]:
        columns = self._raw_columns()
        if columns is None:
            return self._raw._reread()
        return self._raw._read_keeping(columns)

    def _names(self, raw: Sequence[RawSchema]) -> tuple[str, ...]:
        filled = produced_tables(raw, self._bundles, self._schema)
        if self._table is not None:
            return (self._table,) if self._table in filled else ()
        if self._columns is None:
            return filled
        return tuple(name for name in filled if self._shows(name))

    def _shows(self, name: str) -> bool:
        return any(
            column in self._schema[name] for column in self._columns or ()
        )

    def _one(self) -> pa.Table:
        """Read the one table shown, from the block a full read would take.

        The choice is made on the file's whole schemas, so that `columns=`
        changes what is read and never where it is read from.
        """
        raw_tables = self._raw_tables()
        found = (
            tuple(raw.schema for raw in raw_tables)
            if self._columns is None
            else self._raw._schemas()
        )
        name = self._one_name(found)
        chosen = self._source.assigned(found)
        at = chosen.get(name)
        filling = raw_tables if at is None else (raw_tables[at],)
        table = self._source.filled(filling, name)
        if self._joined:
            table = joined_all(table, self._related(raw_tables, name, chosen))
        return self._shown(self._edited(table, name), name)

    def _one_name(self, raw: Sequence[RawSchema]) -> str:
        names = self._names(raw)
        if len(names) == 1:
            return names[0]
        if not names:
            raise _unfilled("a canonical table", self._raw.path)
        raise ValueError(
            f"{self._raw.path} fills {len(names)} canonical tables, "
            f"{', '.join(repr(n) for n in names)}; name the one you mean, "
            "as result[name]"
        )


def _unfilled(what: str, path: str) -> ValueError:
    return ValueError(
        f"No convention fills {what} from {path}; read the file's own "
        "columns through .raw, or pass bundle=, one bundle or several in "
        "priority order"
    )


def _as_polars(table: pa.Table) -> pl.DataFrame:
    import polars as pl

    return pl.DataFrame(table)


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


def _sliced(name: str, table: pa.Table, size: int) -> Iterator[Chunk]:
    for start in range(0, max(table.num_rows, 1), size):
        yield Chunk(name, table.slice(start, size))


def _check_size(size: int) -> None:
    if size < 1:
        raise ValueError(f"A chunk has to hold at least one row, not {size}")
