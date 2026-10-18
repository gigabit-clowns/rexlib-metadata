"""The read engine: raw tables and bundles in, one canonical table out."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa

if TYPE_CHECKING:
    from collections.abc import Iterable

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
    raw_tables = tuple(raw_tables)
    covered: dict[str, pa.Array] = {}

    for bundle in bundles:
        for raw in raw_tables:
            for convention in bundle.read_conventions:
                if not convention.matches(raw.schema):
                    continue
                if all(name in covered for name in convention.target_columns):
                    continue
                produced = convention.load(raw.table)
                for name, array in produced.items():
                    _check_declared(name, schema, bundle, convention)
                    _check_type(name, array, schema, bundle, convention)
                    covered.setdefault(name, array)

    rows = _row_count(covered, schema)
    _check_required(covered, schema)
    return _assemble(covered, schema, rows)


def _check_declared(
    name: str,
    schema: TableSchema,
    bundle: ConventionBundle,
    convention: ReadConvention,
) -> None:
    if name not in schema:
        raise ValueError(
            f"{type(convention).__name__} of bundle '{bundle.name}' "
            f"produced '{name}', which table '{schema.name}' does not "
            "declare"
        )


def _check_type(
    name: str,
    array: pa.Array,
    schema: TableSchema,
    bundle: ConventionBundle,
    convention: ReadConvention,
) -> None:
    declared = schema.column(name).dtype
    if array.type != declared:
        raise TypeError(
            f"{type(convention).__name__} of bundle '{bundle.name}' "
            f"produced '{name}' as {array.type}, where table "
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
