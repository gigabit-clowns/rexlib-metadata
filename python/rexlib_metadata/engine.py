"""The read engine: raw tables and bundles in, one canonical table out."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from rexlib_metadata.convention import (
        ConventionBundle,
        RawTable,
        ReadConvention,
    )
    from rexlib_metadata.schema import ColumnDescriptor, TableSchema


def read_canonical(
    raw_tables: Iterable[RawTable],
    bundles: Iterable[ConventionBundle],
    schema: TableSchema,
) -> pa.Table:
    """Apply the bundles to the raw tables and return the canonical table.

    Bundles are tried in the order given, which is their priority: the
    first one to produce a canonical column owns it, and a later one
    cannot take it back.
    """
    covered: dict[str, pa.Array] = {}

    for bundle, raw, convention in _candidates(bundles, tuple(raw_tables)):
        if not _has_something_to_add(convention, raw, covered):
            continue
        produced = convention.load(raw.table)
        _keep_first(
            covered, produced, convention, schema, _origin(bundle, convention)
        )

    rows = _row_count(covered, schema)
    _check_required(covered, schema)
    return _assemble(covered, schema, rows)


def _candidates(
    bundles: Iterable[ConventionBundle], raw_tables: tuple[RawTable, ...]
) -> Iterator[tuple[ConventionBundle, RawTable, ReadConvention]]:
    for bundle in bundles:
        for raw in raw_tables:
            for convention in bundle.read_conventions:
                yield bundle, raw, convention


def _has_something_to_add(
    convention: ReadConvention, raw: RawTable, covered: dict[str, pa.Array]
) -> bool:
    if not convention.matches(raw.schema):
        return False
    return any(name not in covered for name in convention.target_columns)


def _keep_first(
    covered: dict[str, pa.Array],
    produced: dict[str, pa.Array],
    convention: ReadConvention,
    schema: TableSchema,
    origin: str,
) -> None:
    for name, array in produced.items():
        if name in covered:
            continue
        _check_column(name, array, convention, schema, origin)
        covered[name] = array


def _origin(bundle: ConventionBundle, convention: ReadConvention) -> str:
    return f"{type(convention).__name__} of bundle '{bundle.name}'"


def _check_column(
    name: str,
    array: pa.Array,
    convention: ReadConvention,
    schema: TableSchema,
    origin: str,
) -> None:
    if name not in convention.target_columns:
        raise ValueError(
            f"{origin} produced '{name}', which it does not declare in "
            "target_columns; a bundle can only be checked for ambiguity "
            "against what its conventions say they produce"
        )
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


def _row_count(covered: dict[str, pa.Array], schema: TableSchema) -> int:
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


def _check_required(covered: dict[str, pa.Array], schema: TableSchema) -> None:
    missing = [c.name for c in schema.required_columns if c.name not in covered]
    if missing:
        raise ValueError(
            f"Table '{schema.name}' requires "
            f"{', '.join(repr(name) for name in missing)}, which no "
            "convention produced"
        )


def _assemble(
    covered: dict[str, pa.Array], schema: TableSchema, rows: int
) -> pa.Table:
    names: list[str] = []
    arrays: list[pa.Array] = []
    for column in schema:
        array = covered.get(column.name)
        if array is None:
            if column.default is None:
                continue
            array = _constant(column, rows)
        names.append(column.name)
        arrays.append(array)
    return pa.table(arrays, names=names)


def _constant(column: ColumnDescriptor, rows: int) -> pa.Array:
    return pa.array([column.default] * rows, type=column.dtype)
