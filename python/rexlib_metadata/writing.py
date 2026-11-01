# SPDX-License-Identifier: LGPL-2.1-or-later

"""Canonical tables written as a format spells them, from a file or not."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa

from rexlib_metadata._arrow import as_arrow_table
from rexlib_metadata.convention import RawTable
from rexlib_metadata.engine import write_canonical
from rexlib_metadata.join import joined_all

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

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
    _check_known(arrow, table)
    _check_required(arrow, table)
    return pa.table(
        [
            arrow.column(column).cast(table.column(column).dtype)
            for column in arrow.column_names
        ],
        names=arrow.column_names,
    )


def _table_named(name: str, schema: Schema) -> TableSchema:
    if name not in schema:
        declared = ", ".join(repr(table.name) for table in schema)
        raise KeyError(
            f"No canonical table is called '{name}'; the ones there are "
            f"are {declared}"
        )
    return schema[name]


def _check_known(arrow: pa.Table, table: TableSchema) -> None:
    unknown = [c for c in arrow.column_names if c not in table]
    if unknown:
        raise ValueError(
            f"Table '{table.name}' declares no "
            f"{', '.join(repr(c) for c in unknown)}"
        )


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
