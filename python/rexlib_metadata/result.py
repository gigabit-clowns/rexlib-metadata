# SPDX-License-Identifier: LGPL-2.1-or-later

"""What a read hands back: the canonical view, and the file's own."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import partial, reduce
from itertools import takewhile
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.compute as pc

from rexlib_metadata._arrow import as_arrow_table, to_pandas
from rexlib_metadata.convention import RawSchema, RawTable, as_bundles
from rexlib_metadata.engine import (
    assigned,
    in_context,
    keyed,
    owned,
    produced_tables,
    read_canonical,
    source_columns,
    source_table,
    superseded,
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
        Sequence,
        Set,
    )

    import pandas as pd
    import polars as pl

    from rexlib_metadata.abc import Reader, Writer
    from rexlib_metadata.convention import (
        ArrowColumn,
        ConventionBundle,
        ReadConvention,
    )
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

    def schemas(
        self, columns: Set[str] | None = None
    ) -> tuple[RawSchema, ...]:
        """Name every table and what it has of `columns`, reading no row."""
        if self._tables is None:
            found = self._reader.read_schemas(self._path)
        else:
            found = [table.schema for table in self._tables]
        return _narrowed_all(tuple(found), columns)

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
        _check_declared(self._columns, schema)

    @property
    def raw(self) -> RawResult:
        """The same file, read as it names its own tables and columns."""
        return self._raw

    @property
    def names(self) -> tuple[str, ...]:
        """Name the canonical tables this result shows from this file."""
        return self._names([raw.schema for raw in self._raw_tables()])

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
        found = self._raw.schemas()
        related = self._related_whole(schema.name, found)
        columns = self._raw_columns()
        raw = _narrowed_all(found, columns)
        ordinal = self._ordinal_of(schema, raw)
        if self._schema.related_to(schema.name):
            whole = self._built(schema, raw[ordinal], ordinal, columns)
            for start in range(0, max(whole.num_rows, 1), size):
                yield self._chunk(schema, whole.slice(start, size), related)
            return
        bound = self._bound(schema, raw[ordinal], ordinal)
        for piece in _block_chunks(self._raw, size, ordinal, columns):
            table = self._filled([piece], schema, bound)
            yield self._chunk(schema, table, related)

    def _ordinal_of(
        self, schema: TableSchema, raw: tuple[RawSchema, ...]
    ) -> int:
        ordinal = assigned(raw, self._bundles, self._schema).get(schema.name)
        if ordinal is None:
            raise _unfilled(f"canonical table '{schema.name}'", self._raw.path)
        return ordinal

    def _bound(
        self, schema: TableSchema, raw: RawSchema, at: int
    ) -> dict[int, ReadConvention]:
        """Bind the conventions of `schema` to the whole raw table `at`."""
        chunks = partial(_block_tables, self._raw, at)
        return in_context(raw, self._bundles, schema, chunks)

    def _built(
        self,
        schema: TableSchema,
        raw: RawSchema,
        at: int,
        columns: Set[str] | None,
    ) -> pa.Table:
        """Build a table others point at a chunk at a time, keyed all along."""
        bound = self._bound(schema, raw, at)
        pieces = (
            self._filled([raw], schema, bound)
            for raw in _block_chunks(self._raw, _ROWS, at, columns)
        )
        return reduce(
            lambda built, piece: keyed(
                pa.concat_tables([built, piece]), self._schema, schema.name
            ),
            pieces,
        )

    def _chunk(
        self,
        schema: TableSchema,
        table: pa.Table,
        related: tuple[tuple[Relation, pa.Table], ...],
    ) -> Chunk:
        table = joined_all(table, related)
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
        raw = _narrowed_all(found, columns)
        chosen = assigned(raw, self._bundles, self._schema)
        return tuple(
            (
                relation,
                self._built(
                    self._schema[relation.related],
                    raw[chosen[relation.related]],
                    chosen[relation.related],
                    columns,
                ),
            )
            for relation in self._schema.relations_of(name)
            if relation.related in chosen
        )

    def _related(
        self, raw_tables: tuple[RawTable, ...], name: str
    ) -> tuple[tuple[Relation, pa.Table], ...]:
        raw = [table.schema for table in raw_tables]
        filled = produced_tables(raw, self._bundles, self._schema)
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
        canonical table this result shows. It is read and written a chunk
        at a time, the tables others point at read whole first, unless a
        table others do not point at shares its raw table or `rows` holds
        positions out of order.

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
        plan = self._plan(bundles, same_format)
        if not plan.blocks:
            raise ValueError(
                f"Nothing of {self._raw.path} would reach {path}: no "
                "convention of the destination writes any of its tables"
            )
        edit = self._edit(plan, updates, rows)
        chunks, related, plan = self._sources(plan, edit, rows)
        written = self._rewritten(plan, chunks, related, edit)
        replaced(
            path, lambda temporary: writer.write_chunks(temporary, written)
        )

    def _plan(
        self, bundles: tuple[ConventionBundle, ...], same_format: bool
    ) -> _Plan:
        raw = self._raw.schemas()
        chosen = assigned(raw, self._bundles, self._schema)
        own = owned(raw, self._bundles, self._schema)
        plan_folds = folds(
            produced_tables(raw, self._bundles, self._schema),
            bundles,
            self._schema,
        )
        skipped = folded(plan_folds)
        anew = self._spelled_anew(raw, bundles, own) if same_format else {}
        blocks = tuple(
            _Block(at, name, _carrying(anew, own, name, at))
            for at in range(len(raw))
            for name in _filled_by(chosen, own, at)
            if name not in skipped and (name is not None or same_format)
        )
        return _Plan(raw, chosen, own, bundles, plan_folds, blocks)

    def _spelled_anew(
        self,
        raw: tuple[RawSchema, ...],
        bundles: tuple[ConventionBundle, ...],
        own: dict[str, int],
    ) -> dict[int, frozenset[str]]:
        return {
            at: superseded(raw, self._bundles, bundles, self._schema, at)
            for at in own.values()
        }

    def _edit(
        self,
        plan: _Plan,
        updates: pa.Table | pd.DataFrame | pl.DataFrame | None,
        rows: Rows | None,
    ) -> _Edit | None:
        if updates is None and rows is None:
            return None
        frame = None if updates is None else as_arrow_table(updates)
        return _Edit(self._one_name(plan.raw), frame)

    def _sources(
        self, plan: _Plan, edit: _Edit | None, rows: Rows | None
    ) -> tuple[Iterable[tuple[int, RawTable]], dict[str, pa.Table], _Plan]:
        """Return the chunks to rewrite, the tables needed whole, the plan."""
        needed = self._needed(plan, edit)
        kept = self._kept(edit, rows)
        if self._whole_needed(plan) or (rows is not None and kept is None):
            source = self._source(edit, rows)
            whole = {name: self._canonical(source, name) for name in needed}
            return enumerate(source), whole, plan
        if edit is not None:
            edit.kept = kept
        return self._streamed(plan, needed)

    def _streamed(
        self, plan: _Plan, needed: set[str]
    ) -> tuple[Iterable[tuple[int, RawTable]], dict[str, pa.Table], _Plan]:
        """Return the source in chunks, tables others point at read whole."""
        sharers = plan.sharers()
        raw = self._pointed_at_whole(plan, sharers)
        built = {name: self._shared_whole(plan, name) for name in sharers}
        whole = {
            name: self._whole_of(plan, name, raw, built) for name in needed
        }
        bound = {
            name: self._bound(self._schema[name], plan.raw[at], at)
            for name, at in plan.chosen.items()
            if at not in raw and name not in built
        }
        chunks = _whole_where(self._raw.chunks(_ROWS), raw)
        return chunks, whole, replace(plan, bound=bound, built=built)

    def _pointed_at_whole(
        self, plan: _Plan, sharers: set[str]
    ) -> dict[int, RawTable]:
        """Read whole the raw tables that tables others point at own."""
        return {
            at: self._read_whole(at)
            for name, at in plan.chosen.items()
            if self._schema.related_to(name) and name not in sharers
        }

    def _whole_of(
        self,
        plan: _Plan,
        name: str,
        raw: dict[int, RawTable],
        built: dict[str, pa.Table],
    ) -> pa.Table:
        if name in built:
            return built[name]
        return self._filled([raw[plan.chosen[name]]], self._schema[name])

    def _whole_needed(self, plan: _Plan) -> bool:
        """Say whether a table shares a raw table it is not built from."""
        return any(not self._schema.related_to(n) for n in plan.sharers())

    def _shared_whole(self, plan: _Plan, name: str) -> pa.Table:
        """Build a table others point at from the raw table it shares."""
        schema = self._schema[name]
        at = plan.chosen[name]
        columns = source_columns(
            [column.name for column in schema.columns],
            self._bundles,
            self._schema,
        )
        raw = _narrowed(plan.raw[at], columns)
        return self._built(schema, raw, at, columns)

    def _needed(self, plan: _Plan, edit: _Edit | None) -> set[str]:
        """Name the tables a write needs whole: folded or joined in."""
        if not self._joined or edit is None or edit.updates is None:
            return folded(plan.folds)
        return folded(plan.folds) | {
            relation.related
            for relation in self._schema.relations_of(edit.name)
            if relation.related in plan.chosen
        }

    def _kept(
        self, edit: _Edit | None, rows: Rows | None
    ) -> _Mask | _Positions | None:
        if edit is None or rows is None:
            return None
        if self._schema.related_to(edit.name):
            return None
        return _streamed_rows(rows, edit.name)

    def _source(
        self, edit: _Edit | None, rows: Rows | None
    ) -> tuple[RawTable, ...]:
        source = self._raw.reread()
        if edit is None or rows is None:
            return source
        return self._selected(source, self._schema[edit.name], rows)

    def _read_whole(self, at: int) -> RawTable:
        chunks = takewhile(
            lambda chunk: chunk[0] <= at, self._raw.chunks(_POINTED_AT_ROWS)
        )
        pieces = [raw for ordinal, raw in chunks if ordinal == at]
        table = pa.concat_tables([piece.table for piece in pieces])
        return RawTable(pieces[0].schema, table)

    def _rewritten(
        self,
        plan: _Plan,
        chunks: Iterable[tuple[int, RawTable]],
        related: dict[str, pa.Table],
        edit: _Edit | None,
    ) -> Iterator[tuple[int, RawTable]]:
        seen: set[int] = set()
        for at, raw in chunks:
            blocks = plan.at(at, again=at in seen)
            seen.add(at)
            for ordinal, block in blocks:
                yield ordinal, self._block(raw, block, plan, related, edit)
        if edit is not None:
            edit.check()

    def _block(
        self,
        raw: RawTable,
        block: _Block,
        plan: _Plan,
        related: dict[str, pa.Table],
        edit: _Edit | None,
    ) -> RawTable:
        if block.name is None:
            return raw
        editing = edit if edit is not None and edit.name == block.name else None
        if editing is not None:
            raw = editing.rows_of(raw)
        canonical = self._to_write(raw, block.name, plan, related, editing)
        columns = write_canonical(
            canonical, plan.bundles, self._schema[block.name]
        )
        if block.spelled_anew is not None:
            columns.update(_carried(raw, columns, block.spelled_anew))
        return RawTable.of(
            block.name, pa.table(list(columns.values()), names=list(columns))
        )

    def _to_write(
        self,
        raw: RawTable,
        name: str,
        plan: _Plan,
        related: dict[str, pa.Table],
        editing: _Edit | None,
    ) -> pa.Table:
        """Return canonical table `name` as written: updated, folds joined."""
        schema = self._schema[name]
        canonical = plan.built.get(name)
        if canonical is None:
            canonical = self._filled([raw], schema, plan.bound.get(name))
        updates = (
            None
            if editing is None
            else self._updates_of(editing, canonical, related)
        )
        table = _merged(canonical, updates, schema)
        table = joined_all(
            table, ((r, related[r.related]) for r in plan.folds[name])
        )
        _check_written(table, updates, plan.bundles, schema)
        return table

    def _updates_of(
        self, editing: _Edit, canonical: pa.Table, related: dict[str, pa.Table]
    ) -> pa.Table | None:
        frame = editing.updates_of(canonical.num_rows)
        if frame is None or not self._joined:
            return frame
        name = editing.name
        own = [c for c in frame.column_names if c in self._schema[name]]
        relations = (
            (relation, related[relation.related])
            for relation in self._schema.relations_of(name)
            if relation.related in related
        )
        _check_unchanged(frame, joined_all(canonical, relations), own, name)
        return frame.select(own)

    def _selected(
        self, source: tuple[RawTable, ...], table: TableSchema, rows: Rows
    ) -> tuple[RawTable, ...]:
        filling = source_table(source, self._bundles, self._schema, table.name)
        if filling is None:
            return source
        positions = _positions(rows, filling.table.num_rows, table.name)
        kept = RawTable(filling.schema, filling.table.take(positions))
        return tuple(kept if raw is filling else raw for raw in source)

    def _raw_tables(self) -> tuple[RawTable, ...]:
        columns = self._raw_columns()
        if columns is None:
            return self._raw.reread()
        return self._raw.read_keeping(columns)

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

    def _canonical(
        self, raw_tables: tuple[RawTable, ...], name: str
    ) -> pa.Table:
        return self._filled(raw_tables, self._schema[name])

    def _filled(
        self,
        raw_tables: Iterable[RawTable],
        schema: TableSchema,
        bound: dict[int, ReadConvention] | None = None,
    ) -> pa.Table:
        try:
            return read_canonical(
                raw_tables, self._bundles, self._schema, schema.name, bound
            )
        except pa.ArrowInvalid as error:
            raise ValueError(
                f"{self._raw.path}: canonical table '{schema.name}' holds a "
                f"value that does not parse: {error}"
            ) from error

    def _one(self) -> pa.Table:
        raw_tables = self._raw_tables()
        name = self._one_name([raw.schema for raw in raw_tables])
        table = self._canonical(raw_tables, name)
        if self._joined:
            table = joined_all(table, self._related(raw_tables, name))
        return self._shown(table, name)

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


_ROWS = 100_000
_POINTED_AT_ROWS = 1_000


@dataclass(frozen=True)
class _Block:
    """A block a write produces from raw table `at`, carrying over or not."""

    at: int
    name: str | None
    spelled_anew: frozenset[str] | None


@dataclass(frozen=True)
class _Plan:
    raw: tuple[RawSchema, ...]
    chosen: dict[str, int]
    own: dict[str, int]
    bundles: tuple[ConventionBundle, ...]
    folds: dict[str, tuple[Relation, ...]]
    blocks: tuple[_Block, ...]
    bound: dict[str, dict[int, ReadConvention]] = field(default_factory=dict)
    built: dict[str, pa.Table] = field(default_factory=dict)

    def sharers(self) -> set[str]:
        """Name the tables filled from a raw table another owns."""
        return {
            name
            for name, at in self.chosen.items()
            if self.own.get(name) != at
        }

    def at(self, at: int, again: bool) -> list[tuple[int, _Block]]:
        """Return the blocks raw table `at` is written as, by ordinal.

        `again` leaves out, after its first chunk, the blocks built whole.
        """
        return [
            (n, block)
            for n, block in enumerate(self.blocks)
            if block.at == at and not (again and block.name in self.built)
        ]


class _Edit:
    """What `rows=` and `updates=` change of the one table a write shows."""

    def __init__(self, name: str, updates: pa.Table | None) -> None:
        self.name = name
        self.updates = updates
        self.kept: _Mask | _Positions | None = None
        self._read = 0
        self._written = 0

    def rows_of(self, raw: RawTable) -> RawTable:
        """Return the rows of the next chunk that `rows=` keeps."""
        if self.kept is None:
            return raw
        count = raw.table.num_rows
        picked = self.kept.picked(self._read, count)
        self._read += count
        return RawTable(raw.schema, raw.table.take(picked))

    def updates_of(self, rows: int) -> pa.Table | None:
        """Return the updates of the next `rows` rows written."""
        if self.updates is None:
            return None
        piece = self.updates.slice(self._written, rows)
        self._written += rows
        if piece.num_rows < rows:
            raise _updates_mismatch(
                self.updates, f"at least {self._written}", self.name
            )
        return piece

    def check(self) -> None:
        """Raise if `rows=` or `updates=` did not fit the rows read."""
        if self.kept is not None:
            self.kept.check(self._read)
        if self.updates is not None and self.updates.num_rows != self._written:
            raise _updates_mismatch(self.updates, str(self._written), self.name)


class _Mask:
    def __init__(self, mask: pa.Array, table: str) -> None:
        self._kept = mask
        self._table = table

    def picked(self, start: int, count: int) -> pa.Array:
        return pc.indices_nonzero(
            self._kept.slice(start, count).fill_null(False)
        )

    def check(self, rows: int) -> None:
        if len(self._kept) != rows:
            raise _mask_mismatch(len(self._kept), rows, self._table)


class _Positions:
    def __init__(self, positions: pa.Array, table: str) -> None:
        self._kept = positions
        self._table = table
        self._taken = 0

    def picked(self, start: int, count: int) -> pa.Array:
        window = self._kept.slice(self._taken, count)
        inside = len(
            pc.indices_nonzero(pc.less(window, pa.scalar(start + count)))
        )
        self._taken += inside
        return pc.subtract(window.slice(0, inside), start)

    def check(self, rows: int) -> None:
        if self._taken < len(self._kept):
            raise _outside(self._table, rows)


def _streamed_rows(rows: Rows, table: str) -> _Mask | _Positions | None:
    selection = _as_array(rows)
    if pa.types.is_boolean(selection.type):
        return _Mask(selection, table)
    if _increasing(selection):
        return _Positions(selection.cast(pa.int64()), table)
    return None


def _increasing(selection: pa.Array) -> bool:
    if not pa.types.is_integer(selection.type) or selection.null_count:
        return False
    if not len(selection):
        return True
    positions = selection.cast(pa.int64())
    steps = pc.subtract(
        positions.slice(1), positions.slice(0, len(positions) - 1)
    )
    return (
        positions[0].as_py() >= 0
        and pc.all(pc.greater(steps, pa.scalar(0))).as_py()
    )


def _carrying(
    anew: dict[int, frozenset[str]],
    own: dict[str, int],
    name: str | None,
    at: int,
) -> frozenset[str] | None:
    """Return what a block spells anew, or None if it carries nothing over."""
    if name is None or own.get(name) != at:
        return None
    return anew.get(at)


def _block_chunks(
    raw: RawResult, size: int, at: int, columns: Set[str] | None
) -> Iterator[RawTable]:
    """Yield raw table `at` a chunk at a time, reading no block after it."""
    chunks = takewhile(lambda chunk: chunk[0] <= at, raw.chunks(size, columns))
    yield from (chunk for ordinal, chunk in chunks if ordinal == at)


def _block_tables(
    raw: RawResult, at: int, columns: tuple[str, ...]
) -> Iterator[pa.Table]:
    yield from (
        chunk.table for chunk in _block_chunks(raw, _ROWS, at, set(columns))
    )


def _whole_where(
    chunks: Iterable[tuple[int, RawTable]], whole: dict[int, RawTable]
) -> Iterator[tuple[int, RawTable]]:
    """Put each table of `whole` in the place of its chunks."""
    done: set[int] = set()
    for at, raw in chunks:
        if at not in whole:
            yield at, raw
        elif at not in done:
            done.add(at)
            yield at, whole[at]


def _filled_by(
    chosen: dict[str, int], own: dict[str, int], at: int
) -> list[str | None]:
    """Name the tables raw table `at` is written as: sharers, then its own."""
    names = [name for name, where in chosen.items() if where == at]
    mine = next((name for name in names if own.get(name) == at), None)
    return [*(name for name in names if name != mine), mine]


def _carried(
    raw: RawTable, written: dict[str, ArrowColumn], spelled_anew: frozenset[str]
) -> dict[str, ArrowColumn]:
    """Return what the write leaves of the raw table the read drew on."""
    return {
        column: raw.table.column(column)
        for column in raw.table.column_names
        if column not in written and column not in spelled_anew
    }


def _unfilled(what: str, path: str) -> ValueError:
    return ValueError(
        f"No convention fills {what} from {path}; read the file's own "
        "columns through .raw, or pass bundle=, one bundle or several in "
        "priority order"
    )


def _narrowed(raw: RawSchema, columns: Set[str]) -> RawSchema:
    kept = tuple(name for name in raw.column_names if name in columns)
    return RawSchema(raw.table_name, kept)


def _narrowed_all(
    found: tuple[RawSchema, ...], columns: Set[str] | None
) -> tuple[RawSchema, ...]:
    if columns is None:
        return found
    return tuple(_narrowed(raw, columns) for raw in found)


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


def _merged(
    canonical: pa.Table,
    updates: pa.Table | pd.DataFrame | pl.DataFrame | None,
    schema: TableSchema,
) -> pa.Table:
    """Return `canonical` with the columns of `updates` in place of its own."""
    if updates is None:
        return canonical
    changed = as_arrow_table(updates)
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


def _updates_mismatch(updates: pa.Table, written: str, name: str) -> ValueError:
    return ValueError(
        f"updates holds {updates.num_rows} rows where {written} of table "
        f"'{name}' are written; it holds one per row written, in the same "
        "order: one per row of the table, or one per row rows= keeps"
    )


def _mask_mismatch(length: int, count: int, table: str) -> ValueError:
    return ValueError(
        f"rows is a mask of {length} where table '{table}' holds {count} rows"
    )


def _outside(table: str, count: int) -> ValueError:
    return ValueError(
        f"rows names a row outside table '{table}', which holds {count}"
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
            raise _mask_mismatch(len(selection), count, table)
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
        raise _outside(table, count)
    return selection.cast(pa.int64())


def _as_array(rows: Rows) -> pa.Array:
    to_arrow = getattr(rows, "to_arrow", None)
    found = rows if to_arrow is None else to_arrow()
    if isinstance(found, pa.ChunkedArray):
        return found.combine_chunks()
    if isinstance(found, pa.Array):
        return found
    return pa.array(found)
