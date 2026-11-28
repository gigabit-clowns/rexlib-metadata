# SPDX-License-Identifier: LGPL-2.1-or-later

"""Canonical tables written as a format spells them, from a file or not."""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa

from rexlib_metadata._arrow import as_arrow_table
from rexlib_metadata.convention import RawTable
from rexlib_metadata.engine import write_canonical
from rexlib_metadata.join import joined_all

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from rexlib_metadata._arrow import Frame
    from rexlib_metadata.convention import ConventionBundle
    from rexlib_metadata.schema import Relation, Schema, TableSchema


def folds(
    names: tuple[str, ...],
    bundles: tuple[ConventionBundle, ...],
    schema: Schema,
) -> dict[str, tuple[Relation, ...]]:
    """Say, per table, which tables it points at that go in its rows.

    A related table the destination's conventions do not write is joined
    into the table that points at it, so that a format with no table for
    it, as XMD has none for the optics, still gets them.
    """
    return {
        name: tuple(
            relation
            for relation in schema.relations_of(name)
            if relation.related in names
            and not any(b.write_conventions(relation.related) for b in bundles)
        )
        for name in names
    }


def folded(plan: dict[str, tuple[Relation, ...]]) -> set[str]:
    """Return the tables a plan joins into others rather than writes."""
    return {r.related for relations in plan.values() for r in relations}


def written_frames(
    tables: Mapping[str, pa.Table],
    bundles: tuple[ConventionBundle, ...],
    schema: Schema,
) -> list[RawTable]:
    """Spell canonical tables as the bundles write them, folds joined in.

    A table others point at comes first, the optics before the particles,
    as Relion writes them: a reader taking the first block that fills a
    table would otherwise find the optics group among the particles.
    """
    plan = folds(tuple(tables), bundles, schema)
    skipped = folded(plan)
    pointed_at = [name for name in tables if schema.related_to(name)]
    ordered = pointed_at + [name for name in tables if name not in pointed_at]
    return [
        RawTable.of(name, _spelled(name, tables, plan, bundles, schema))
        for name in ordered
        if name not in skipped
    ]


def _spelled(
    name: str,
    tables: Mapping[str, pa.Table],
    plan: dict[str, tuple[Relation, ...]],
    bundles: tuple[ConventionBundle, ...],
    schema: Schema,
) -> pa.Table:
    related = ((relation, tables[relation.related]) for relation in plan[name])
    table = joined_all(tables[name], related)
    columns = write_canonical(table, bundles, schema[name])
    return pa.table(list(columns.values()), names=list(columns))


def canonical_frame(name: str, frame: Frame, schema: Schema) -> pa.Table:
    """Return `frame` as canonical table `name`, each column as declared."""
    table = _table_named(name, schema)
    arrow = as_arrow_table(frame)
    typed_frame = typed(arrow, [table], f"frame '{name}'")
    _check_required(arrow, table)
    return typed_frame


def typed(
    frame: pa.Table, tables: Sequence[TableSchema], what: str
) -> pa.Table:
    """Return `frame` with each column cast to the type `tables` declare.

    A column none of `tables` declares, or a value its declared type
    cannot hold, raises, naming the frame as `what`.
    """
    return pa.table(
        [_cast(frame, column, tables, what) for column in frame.column_names],
        names=frame.column_names,
    )


def _cast(
    frame: pa.Table, column: str, tables: Sequence[TableSchema], what: str
) -> pa.ChunkedArray:
    declared = next((t.column(column) for t in tables if column in t), None)
    if declared is None:
        shown = ", ".join(repr(t.name) for t in tables)
        raise ValueError(
            f"{what} holds '{column}', which no table of {shown} declares"
        )
    try:
        return frame.column(column).cast(declared.dtype)
    except (pa.ArrowInvalid, pa.ArrowNotImplementedError) as error:
        raise ValueError(
            f"{what} column '{column}' holds a value its declared type, "
            f"{declared.dtype}, cannot hold: {error}"
        ) from error


def _table_named(name: str, schema: Schema) -> TableSchema:
    if name not in schema:
        declared = ", ".join(repr(table.name) for table in schema)
        raise KeyError(
            f"No canonical table is called '{name}'; the ones there are "
            f"are {declared}"
        )
    return schema[name]


def _check_required(arrow: pa.Table, table: TableSchema) -> None:
    missing = [
        column.name
        for column in table.columns
        if column.required and column.name not in arrow.column_names
    ]
    if missing:
        raise ValueError(
            f"Table '{table.name}' requires "
            f"{', '.join(repr(c) for c in missing)}"
        )


def replaced(path: str, write: Callable[[str], None]) -> None:
    """Write through a file beside `path`, moved over it once written.

    The file keeps the mode `path` had, or takes a new file's.
    """
    destination = Path(path)
    temporary = _created_beside(destination)
    try:
        write(str(temporary))
        if destination.exists():
            temporary.chmod(stat.S_IMODE(destination.stat().st_mode))
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _created_beside(destination: Path) -> Path:
    """Create an empty file beside `destination`, with a new file's mode."""
    while True:
        candidate = destination.with_name(
            f".{destination.stem}.{secrets.token_hex(6)}{destination.suffix}"
        )
        try:
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            os.close(os.open(candidate, flags, 0o666))
        except FileExistsError:
            continue
        return candidate
