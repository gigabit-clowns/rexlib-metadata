# SPDX-License-Identifier: LGPL-2.1-or-later

"""The read engine: raw tables and bundles in, one canonical table out."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from rexlib_metadata.convention import (
        ArrowColumn,
        ConventionBundle,
        RawSchema,
        RawTable,
        ReadConvention,
        WriteConvention,
    )
    from rexlib_metadata.schema import (
        ColumnDescriptor,
        Schema,
        TableSchema,
    )


def read_canonical(
    raw_tables: Iterable[RawTable],
    bundles: Iterable[ConventionBundle],
    schema: Schema,
    name: str,
) -> pa.Table:
    """Apply the bundles to the raw tables and return canonical table `name`.

    One raw table fills it, the one `assigned` gives it. Within that table,
    bundles are tried in the order given, which is their priority: the
    first one to produce a canonical column owns it, and a later one cannot
    take it back.
    """
    raw_tables = tuple(raw_tables)
    bundles = tuple(bundles)
    table = schema[name]
    _check_anything_was_understood(raw_tables, bundles, table)
    source = source_table(raw_tables, bundles, schema, name)
    covered = _read_from(source, bundles, table) if source else {}
    rows = _row_count(covered, table)
    _check_required(covered, table)
    return _assemble(covered, table, rows)


def assigned(
    raw: Sequence[RawSchema],
    bundles: Iterable[ConventionBundle],
    schema: Schema,
) -> dict[str, int]:
    """Say which raw table, by its position, fills each canonical table.

    A raw table can fill a canonical one when its matching conventions
    declare every column the canonical table requires, and the pair scores
    the columns they declare. Best score first, then file order, then
    schema order, a pair is taken when neither table is taken yet. A
    canonical table left with no raw table of its own then shares the best
    one it can fill.
    """
    pairs = _pairs(raw, tuple(bundles), schema)
    chosen: dict[str, int] = {}
    for at, name in pairs:
        if name not in chosen and at not in chosen.values():
            chosen[name] = at
    for at, name in pairs:
        chosen.setdefault(name, at)
    return chosen


def source_table(
    raw_tables: Sequence[RawTable],
    bundles: Iterable[ConventionBundle],
    schema: Schema,
    name: str,
) -> RawTable | None:
    """Return the raw table canonical table `name` fills from, if any."""
    raw = [table.schema for table in raw_tables]
    at = assigned(raw, bundles, schema).get(name)
    return None if at is None else raw_tables[at]


def _pairs(
    raw: Sequence[RawSchema],
    bundles: tuple[ConventionBundle, ...],
    schema: Schema,
) -> list[tuple[int, str]]:
    scored = sorted(
        (-len(declared), at, order, table.name)
        for order, table in enumerate(schema)
        for at, one in enumerate(raw)
        if _can_fill(table, declared := _declared_by(table, one, bundles))
    )
    return [(at, name) for _, at, _, name in scored]


def write_canonical(
    table: pa.Table,
    bundles: Iterable[ConventionBundle],
    schema: TableSchema,
) -> dict[str, ArrowColumn]:
    """Turn a canonical table into the columns one format writes.

    Bundles are tried in the order given, which is their priority: the
    first one to produce a file column owns it.
    """
    bundles = tuple(bundles)
    canonical: dict[str, ArrowColumn] = {
        name: table.column(name) for name in table.column_names
    }
    produced: dict[str, ArrowColumn] = {}

    for bundle, convention in _stores(bundles, schema):
        if not _has_something_to_write(convention, canonical, produced):
            continue
        _keep_first_written(
            produced, convention.store(canonical), convention, bundle
        )

    _check_anything_was_written(produced, bundles, schema)
    return produced


def written_from(
    columns: Iterable[str],
    bundles: Iterable[ConventionBundle],
    schema: TableSchema,
) -> set[str]:
    """Return the canonical columns a write of `columns` would consume."""
    present = set(columns)
    return {
        name
        for _, convention in _stores(tuple(bundles), schema)
        if all(column in present for column in convention.source_columns)
        for name in convention.source_columns
    }


def _stores(
    bundles: tuple[ConventionBundle, ...], schema: TableSchema
) -> Iterator[tuple[ConventionBundle, WriteConvention]]:
    return (
        (bundle, convention)
        for bundle in bundles
        for convention in bundle.write_conventions(schema.name)
    )


def _has_something_to_write(
    convention: WriteConvention,
    canonical: dict[str, ArrowColumn],
    produced: dict[str, ArrowColumn],
) -> bool:
    if not all(name in canonical for name in convention.source_columns):
        return False
    return any(name not in produced for name in convention.target_columns)


def _keep_first_written(
    produced: dict[str, ArrowColumn],
    stored: dict[str, ArrowColumn],
    convention: WriteConvention,
    bundle: ConventionBundle,
) -> None:
    origin = _origin(bundle, convention)
    for name, column in stored.items():
        if name in produced:
            continue
        _check_target(name, convention, origin)
        produced[name] = column


def _check_target(
    name: str, convention: ReadConvention | WriteConvention, origin: str
) -> None:
    if name not in convention.target_columns:
        raise ValueError(
            f"{origin} produced '{name}', which it does not declare in "
            "target_columns; a bundle can only be checked for ambiguity "
            "against what its conventions say they produce"
        )


def _check_anything_was_written(
    produced: dict[str, ArrowColumn],
    bundles: tuple[ConventionBundle, ...],
    schema: TableSchema,
) -> None:
    if produced:
        return
    raise ValueError(
        f"No convention of {_bundle_names(bundles)} writes canonical table "
        f"'{schema.name}', so the file would hold nothing. Register a bundle "
        "for this format, pass one as bundle=, or write the file's own "
        "columns through .raw"
    )


def _read_from(
    source: RawTable,
    bundles: tuple[ConventionBundle, ...],
    schema: TableSchema,
) -> dict[str, ArrowColumn]:
    covered: dict[str, ArrowColumn] = {}
    for bundle, convention in _candidates(bundles, schema):
        if not _has_something_to_add(convention, source, covered):
            continue
        produced = convention.load(source.table)
        _keep_first(
            covered, produced, convention, schema, _origin(bundle, convention)
        )
    return covered


def _candidates(
    bundles: Iterable[ConventionBundle], schema: TableSchema
) -> Iterator[tuple[ConventionBundle, ReadConvention]]:
    return (
        (bundle, convention)
        for bundle in bundles
        for convention in bundle.read_conventions(schema.name)
    )


def produced_tables(
    raw_tables: Iterable[RawTable],
    bundles: Iterable[ConventionBundle],
    schema: Schema,
) -> tuple[str, ...]:
    """Name the canonical tables these bundles can fill from these raw ones.

    A table is named when one raw table's matching conventions declare
    every column it requires, which is the rule a read follows, asked of
    the schemas alone before a value is read.
    """
    chosen = assigned([raw.schema for raw in raw_tables], bundles, schema)
    return tuple(table.name for table in schema if table.name in chosen)


def source_columns(
    columns: Iterable[str],
    bundles: Iterable[ConventionBundle],
    schema: Schema,
) -> frozenset[str]:
    """Name the raw columns a read of canonical `columns` has to keep.

    A table declaring one of `columns` keeps what its conventions read
    to produce those and every column the table requires, so that it can
    still be filled. A convention decides `matches()` from its
    `source_columns`, which is what makes the set knowable before a header
    is read. It may name more than a file holds, and never less than a
    read of `columns` needs.
    """
    columns = frozenset(columns)
    bundles = tuple(bundles)
    return frozenset(
        name
        for table in schema
        if any(column in table for column in columns)
        for _, convention in _candidates(bundles, table)
        if _wanted(table, columns).intersection(convention.target_columns)
        for name in convention.source_columns
    )


def _wanted(table: TableSchema, columns: frozenset[str]) -> set[str]:
    return {name for name in columns if name in table} | {
        column.name for column in table.required_columns
    }


def _can_fill(table: TableSchema, declared: set[str]) -> bool:
    return all(column.name in declared for column in table.required_columns)


def _declared_by(
    schema: TableSchema,
    raw: RawSchema,
    bundles: tuple[ConventionBundle, ...],
) -> set[str]:
    return {
        name
        for _, convention in _candidates(bundles, schema)
        if convention.matches(raw)
        for name in convention.target_columns
    }


def _check_anything_was_understood(
    raw_tables: tuple[RawTable, ...],
    bundles: tuple[ConventionBundle, ...],
    schema: TableSchema,
) -> None:
    if not any(raw.table.num_rows for raw in raw_tables):
        return
    if any(_declared_by(schema, raw.schema, bundles) for raw in raw_tables):
        return
    raise ValueError(
        f"No convention of {_bundle_names(bundles)} understood a single "
        f"column of {_raw_names(raw_tables)}, so canonical table "
        f"'{schema.name}' would come back empty where the file has rows. "
        "Register a bundle for this format, pass one as bundle=, or read "
        "the file's own columns through .raw"
    )


def _bundle_names(bundles: tuple[ConventionBundle, ...]) -> str:
    if not bundles:
        return "the none registered"
    return ", ".join(repr(bundle.name) for bundle in bundles)


def _raw_names(raw_tables: tuple[RawTable, ...]) -> str:
    return "; ".join(
        f"'{raw.schema.table_name}' ("
        + ", ".join(raw.schema.column_names)
        + ")"
        for raw in raw_tables
    )


def _has_something_to_add(
    convention: ReadConvention, raw: RawTable, covered: dict[str, ArrowColumn]
) -> bool:
    if not convention.matches(raw.schema):
        return False
    return any(name not in covered for name in convention.target_columns)


def _keep_first(
    covered: dict[str, ArrowColumn],
    produced: dict[str, ArrowColumn],
    convention: ReadConvention,
    schema: TableSchema,
    origin: str,
) -> None:
    for name, array in produced.items():
        if name in covered:
            continue
        _check_column(name, array, convention, schema, origin)
        covered[name] = array


def _origin(
    bundle: ConventionBundle, convention: ReadConvention | WriteConvention
) -> str:
    return f"{type(convention).__name__} of bundle '{bundle.name}'"


def _check_column(
    name: str,
    array: ArrowColumn,
    convention: ReadConvention,
    schema: TableSchema,
    origin: str,
) -> None:
    _check_target(name, convention, origin)
    if name not in schema:
        raise ValueError(
            f"{origin} produced '{name}', which table '{schema.name}' does "
            "not declare"
        )
    declared = schema.column(name).dtype
    if array.type != declared:
        raise TypeError(
            f"{origin} produced '{name}' as {array.type}, where table "
            f"'{schema.name}' declares {declared}; a convention converts, "
            "the engine does not"
        )


def _row_count(covered: dict[str, ArrowColumn], schema: TableSchema) -> int:
    lengths = {name: len(array) for name, array in covered.items()}
    if not lengths:
        return 0
    if len(set(lengths.values())) > 1:
        shapes = ", ".join(f"'{n}' has {c}" for n, c in lengths.items())
        raise ValueError(
            f"The conventions of table '{schema.name}' produced columns of "
            f"different lengths: {shapes}. A column read from another table, "
            "optics being the case that exists, has to be expanded to one "
            "value per row by the convention that reads it"
        )
    return next(iter(lengths.values()))


def _check_required(
    covered: dict[str, ArrowColumn], schema: TableSchema
) -> None:
    missing = [c.name for c in schema.required_columns if c.name not in covered]
    if missing:
        raise ValueError(
            f"Table '{schema.name}' requires "
            f"{', '.join(repr(name) for name in missing)}, which no "
            "convention produced"
        )


def _assemble(
    covered: dict[str, ArrowColumn], schema: TableSchema, rows: int
) -> pa.Table:
    columns = {
        column.name: _column(column, covered, rows)
        for column in schema
        if column.name in covered or column.default is not None
    }
    return pa.table(list(columns.values()), names=list(columns))


def _column(
    column: ColumnDescriptor, covered: dict[str, ArrowColumn], rows: int
) -> ArrowColumn:
    if column.name in covered:
        return covered[column.name]
    return pa.array([column.default] * rows, type=column.dtype)
