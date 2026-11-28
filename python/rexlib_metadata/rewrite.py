# SPDX-License-Identifier: LGPL-2.1-or-later

"""Rewriting the file a canonical view was read from, a chunk at a time."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.compute as pc

from rexlib_metadata import reading
from rexlib_metadata._arrow import as_arrow_table
from rexlib_metadata.convention import RawTable
from rexlib_metadata.engine import (
    in_context,
    owned,
    produced_tables,
    source_columns,
    superseded,
    write_canonical,
    written_from,
)
from rexlib_metadata.join import joined_all
from rexlib_metadata.reading import block_chunks, narrowed
from rexlib_metadata.writing import folded, folds, replaced, typed

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator

    import pandas as pd
    import polars as pl

    from rexlib_metadata.abc import Writer
    from rexlib_metadata.convention import (
        ArrowColumn,
        ConventionBundle,
        RawSchema,
        ReadConvention,
    )
    from rexlib_metadata.reading import Reading
    from rexlib_metadata.registry import MetadataRegistry
    from rexlib_metadata.schema import Relation, TableSchema

    Rows = Collection[int] | Collection[bool] | pa.Array | pa.ChunkedArray
    Updates = pa.Table | pd.DataFrame | pl.DataFrame

_POINTED_AT_ROWS = 1_000


class Rewrite:
    """A write of the whole file a canonical view was read from."""

    def __init__(
        self,
        source: Reading,
        joined: bool,
        writer: Writer,
        bundles: tuple[ConventionBundle, ...],
    ) -> None:
        """Rewrite what `source` reads through `writer` and `bundles`.

        `joined` says whether the view showed its related tables joined in.
        """
        self._source = source
        self._schema = source.schema
        self._joined = joined
        self._writer = writer
        self._bundles = bundles

    def write(
        self,
        path: str,
        shown: str | None,
        updates: Updates | None,
        rows: Rows | None,
    ) -> None:
        """Write the source to `path`, `shown` edited by `updates`, `rows`."""
        raw = self._source.raw
        same_format = _same_writer(
            self._writer, _writer_of(raw.registry, raw.path)
        )
        plan = self._plan(same_format)
        if not plan.blocks:
            raise ValueError(
                f"Nothing of {raw.path} would reach {path}: no convention of "
                "the destination writes any of its tables"
            )
        edit = self._edit(plan, shown, updates, rows)
        sources = self._sources(plan, edit, rows)
        if edit is not None and edit.name in folded(plan.folds):
            sources.whole[edit.name] = self._folded_edit(
                edit, plan, sources.whole, rows, path
            )
        written = self._rewritten(plan, sources, edit)
        replaced(
            path,
            lambda temporary: self._writer.write_chunks(temporary, written),
        )

    def _folded_edit(
        self,
        edit: _Edit,
        plan: _Plan,
        whole: dict[str, pa.Table],
        rows: Rows | None,
        path: str,
    ) -> pa.Table:
        """Apply `updates` to a table the destination folds into others.

        A column of `updates` that the tables folding it do not write
        raises, as it does for the table a write shows.
        """
        if rows is not None:
            raise ValueError(
                f"rows= selects rows of '{edit.name}', which {path} has no "
                "table for and joins into the rows that point at it"
            )
        table = whole[edit.name]
        changes = edit.updates_of(table.num_rows)
        if changes is not None:
            self._check_folded(edit.name, changes, plan)
        return _merged(table, changes)

    def _check_folded(self, name: str, changes: pa.Table, plan: _Plan) -> None:
        folders = [
            folder
            for folder, relations in plan.folds.items()
            if any(relation.related == name for relation in relations)
        ]
        consumed = {
            column
            for folder in folders
            for column in written_from(
                [
                    *(c.name for c in self._schema[folder]),
                    *changes.column_names,
                ],
                self._bundles,
                self._schema[folder],
            )
        }
        lost = [n for n in changes.column_names if n not in consumed]
        if lost:
            raise ValueError(
                f"updates holds {', '.join(repr(n) for n in lost)}, which no "
                f"convention writes once '{name}' is joined into "
                f"{', '.join(repr(f) for f in folders)}, so the change would "
                "not reach the file"
            )

    def _plan(self, same_format: bool) -> _Plan:
        source = self._source
        raw = source.raw._schemas()
        chosen = source.assigned(raw)
        own = owned(raw, source.bundles, self._schema)
        plan_folds = folds(
            produced_tables(raw, source.bundles, self._schema),
            self._bundles,
            self._schema,
        )
        skipped = folded(plan_folds)
        anew = self._spelled_anew(raw, chosen, own) if same_format else {}
        blocks = tuple(
            _Block(at, name, _carrying(anew, own, name, at))
            for at in range(len(raw))
            for name in _filled_by(chosen, own, at)
            if name not in skipped and (name is not None or same_format)
        )
        return _Plan(raw, chosen, own, plan_folds, blocks)

    def _spelled_anew(
        self,
        raw: tuple[RawSchema, ...],
        chosen: dict[str, int],
        own: dict[str, int],
    ) -> dict[int, frozenset[str]]:
        return {
            at: superseded(
                raw[at],
                [self._schema[n] for n, where in chosen.items() if where == at],
                self._source.bundles,
                self._bundles,
            )
            for at in own.values()
        }

    def _edit(
        self,
        plan: _Plan,
        shown: str | None,
        updates: Updates | None,
        rows: Rows | None,
    ) -> _Edit | None:
        if shown is None:
            return None
        frame = None
        if updates is not None:
            frame = as_arrow_table(updates)
            frame = typed(frame, self._shown(shown), "updates")
        kept = None
        if rows is not None and not self._whole_needed(plan):
            kept = self._kept(shown, rows)
        return _Edit(shown, frame, kept)

    def _shown(self, name: str) -> list[TableSchema]:
        """Name the tables a write of `name` shows: it, and what it joins."""
        tables = [self._schema[name]]
        if self._joined:
            tables += [
                self._schema[r.related] for r in self._schema.relations_of(name)
            ]
        return tables

    def _sources(
        self, plan: _Plan, edit: _Edit | None, rows: Rows | None
    ) -> _Sources:
        needed = self._needed(plan, edit)
        selects = edit is not None and rows is not None and edit.kept is None
        if self._whole_needed(plan) or selects:
            return self._whole(plan, needed, edit, rows)
        return self._streamed(plan, needed)

    def _whole(
        self,
        plan: _Plan,
        needed: set[str],
        edit: _Edit | None,
        rows: Rows | None,
    ) -> _Sources:
        """Return the source read whole, as `_streamed` would see it.

        `rows` selects rows of the shown table only: what the other tables
        hold, and the context its conventions number from, are the whole
        file's.
        """
        source = self._source
        every = source.raw._reread()
        chunks = every
        if edit is not None and rows is not None:
            at = plan.chosen.get(edit.name)
            chunks = _selected(every, edit.name, at, rows)
        built = {
            name: source.filled(every, name)
            for name in plan.sharers()
            if self._schema.related_to(name)
        }
        bound = {
            name: in_context(
                plan.raw[at],
                source.bundles,
                self._schema[name],
                partial(_as_chunks, every[at].table),
            )
            for name, at in plan.chosen.items()
            if name not in built
        }
        whole = {name: source.filled(every, name) for name in needed}
        return _Sources(enumerate(chunks), whole, bound, built)

    def _streamed(self, plan: _Plan, needed: set[str]) -> _Sources:
        """Return the source in chunks, tables others point at read whole."""
        sharers = plan.sharers()
        raw = self._pointed_at_whole(plan, sharers)
        built = {name: self._shared_whole(plan, name) for name in sharers}
        whole = {
            name: self._whole_of(plan, name, raw, built) for name in needed
        }
        bound = {
            name: self._source.bound(name, plan.raw[at], at)
            for name, at in plan.chosen.items()
            if at not in raw and name not in built
        }
        chunks = _whole_where(self._source.raw._chunks(reading.ROWS), raw)
        return _Sources(chunks, whole, bound, built)

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
        return self._source.filled([raw[plan.chosen[name]]], name)

    def _whole_needed(self, plan: _Plan) -> bool:
        """Say whether a table shares a raw table it is not built from."""
        return any(not self._schema.related_to(n) for n in plan.sharers())

    def _shared_whole(self, plan: _Plan, name: str) -> pa.Table:
        """Build a table others point at from the raw table it shares."""
        at = plan.chosen[name]
        columns = source_columns(
            [column.name for column in self._schema[name].columns],
            self._source.bundles,
            self._schema,
        )
        raw = narrowed(plan.raw[at], columns)
        return self._source.built(name, raw, at, columns)

    def _needed(self, plan: _Plan, edit: _Edit | None) -> set[str]:
        """Name the tables a write needs whole: folded or joined in."""
        if not self._joined or edit is None or edit.updates is None:
            return folded(plan.folds)
        return folded(plan.folds) | {
            relation.related
            for relation in self._schema.relations_of(edit.name)
            if relation.related in plan.chosen
        }

    def _kept(self, name: str, rows: Rows) -> _Mask | _Positions | None:
        if self._schema.related_to(name):
            return None
        return _streamed_rows(rows, name)

    def _read_whole(self, at: int) -> RawTable:
        pieces = list(
            block_chunks(self._source.raw, _POINTED_AT_ROWS, at, None)
        )
        table = pa.concat_tables([piece.table for piece in pieces])
        return RawTable(pieces[0].schema, table)

    def _rewritten(
        self, plan: _Plan, sources: _Sources, edit: _Edit | None
    ) -> Iterator[tuple[int, RawTable]]:
        seen: set[int] = set()
        for at, raw in sources.chunks:
            blocks = plan.at(at, again=at in seen, built=sources.built)
            seen.add(at)
            for ordinal, block in blocks:
                yield ordinal, self._block(raw, block, plan, sources, edit)
        if edit is not None:
            edit.check()

    def _block(
        self,
        raw: RawTable,
        block: _Block,
        plan: _Plan,
        sources: _Sources,
        edit: _Edit | None,
    ) -> RawTable:
        if block.name is None:
            return raw
        editing = edit if edit is not None and edit.name == block.name else None
        if editing is not None:
            raw = editing.rows_of(raw)
        canonical = self._to_write(raw, block.name, plan, sources, editing)
        columns = write_canonical(
            canonical, self._bundles, self._schema[block.name]
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
        sources: _Sources,
        editing: _Edit | None,
    ) -> pa.Table:
        """Return canonical table `name` as written: updated, folds joined."""
        schema = self._schema[name]
        canonical = sources.built.get(name)
        if canonical is None:
            canonical = self._source.filled(
                [raw], name, sources.bound.get(name)
            )
        updates = (
            None
            if editing is None
            else self._updates_of(editing, canonical, sources.whole)
        )
        table = _merged(canonical, updates)
        table = joined_all(
            table, ((r, sources.whole[r.related]) for r in plan.folds[name])
        )
        _check_written(table, updates, self._bundles, schema)
        return table

    def _updates_of(
        self, editing: _Edit, canonical: pa.Table, whole: dict[str, pa.Table]
    ) -> pa.Table | None:
        frame = editing.updates_of(canonical.num_rows)
        if frame is None or not self._joined:
            return frame
        name = editing.name
        own = [c for c in frame.column_names if c in self._schema[name]]
        relations = (
            (relation, whole[relation.related])
            for relation in self._schema.relations_of(name)
            if relation.related in whole
        )
        _check_unchanged(frame, joined_all(canonical, relations), own, name)
        return frame.select(own)


@dataclass(frozen=True)
class _Block:
    """A block a write produces from raw table `at`, carrying over or not."""

    at: int
    name: str | None
    spelled_anew: frozenset[str] | None


@dataclass(frozen=True)
class _Plan:
    """Which blocks a write produces, and from which raw tables."""

    raw: tuple[RawSchema, ...]
    chosen: dict[str, int]
    own: dict[str, int]
    folds: dict[str, tuple[Relation, ...]]
    blocks: tuple[_Block, ...]

    def sharers(self) -> set[str]:
        """Name the tables filled from a raw table another owns."""
        return {
            name
            for name, at in self.chosen.items()
            if self.own.get(name) != at
        }

    def at(
        self, at: int, again: bool, built: dict[str, pa.Table]
    ) -> list[tuple[int, _Block]]:
        """Return the blocks raw table `at` is written as, by ordinal.

        `again` leaves out, after its first chunk, the blocks `built` holds.
        """
        return [
            (n, block)
            for n, block in enumerate(self.blocks)
            if block.at == at and not (again and block.name in built)
        ]


@dataclass(frozen=True)
class _Sources:
    """What a write reads: the chunks, and the tables it holds whole."""

    chunks: Iterable[tuple[int, RawTable]]
    whole: dict[str, pa.Table]
    bound: dict[str, dict[int, ReadConvention]]
    built: dict[str, pa.Table]


class _Edit:
    """What `rows=` and `updates=` change of the one table a write shows."""

    def __init__(
        self,
        name: str,
        updates: pa.Table | None,
        kept: _Mask | _Positions | None,
    ) -> None:
        self.name = name
        self.updates = updates
        self.kept = kept
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


def _selected(
    source: tuple[RawTable, ...],
    name: str,
    at: int | None,
    rows: Rows,
) -> tuple[RawTable, ...]:
    if at is None:
        return source
    filling = source[at]
    positions = _positions(rows, filling.table.num_rows, name)
    kept = RawTable(filling.schema, filling.table.take(positions))
    return (*source[:at], kept, *source[at + 1 :])


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


def _as_chunks(table: pa.Table, _columns: tuple[str, ...]) -> list[pa.Table]:
    return [table]


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


def _merged(canonical: pa.Table, updates: pa.Table | None) -> pa.Table:
    """Return `canonical` with the columns of `updates` in place of its own."""
    if updates is None:
        return canonical
    for name in updates.column_names:
        column = updates.column(name)
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
    updates: pa.Table | None,
    bundles: tuple[ConventionBundle, ...],
    schema: TableSchema,
) -> None:
    if updates is None:
        return
    consumed = written_from(canonical.column_names, bundles, schema)
    lost = [name for name in updates.column_names if name not in consumed]
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
    array = found if isinstance(found, pa.Array) else pa.array(found)
    if pa.types.is_null(array.type) and not len(array):
        return array.cast(pa.int64())
    return array
