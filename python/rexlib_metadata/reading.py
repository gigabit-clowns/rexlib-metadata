# SPDX-License-Identifier: LGPL-2.1-or-later

"""The canonical tables of one file, built from its raw ones."""

from __future__ import annotations

from functools import partial, reduce
from itertools import takewhile
from typing import TYPE_CHECKING

import pyarrow as pa

from rexlib_metadata.convention import RawSchema
from rexlib_metadata.engine import assigned, in_context, keyed, read_canonical

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Set

    from rexlib_metadata.convention import (
        ConventionBundle,
        RawTable,
        ReadConvention,
    )
    from rexlib_metadata.result import RawResult
    from rexlib_metadata.schema import Schema

ROWS = 100_000


class Reading:
    """A file's raw tables, turned canonical by the bundles it is read with."""

    def __init__(
        self,
        raw: RawResult,
        bundles: tuple[ConventionBundle, ...],
        schema: Schema,
        rows: int = ROWS,
    ) -> None:
        """Read `raw` through `bundles` into the tables of `schema`.

        A table read whole, to build it or bind its conventions, is read
        `rows` rows at a time.
        """
        self.raw = raw
        self.bundles = bundles
        self.schema = schema
        self.rows = rows

    def sized(self, rows: int) -> Reading:
        """Return the same reading, `rows` rows at a time."""
        return Reading(self.raw, self.bundles, self.schema, rows)

    def assigned(self, found: tuple[RawSchema, ...]) -> dict[str, int]:
        """Name the raw table each canonical table is filled from."""
        return assigned(found, self.bundles, self.schema)

    def filled(
        self,
        raw_tables: Iterable[RawTable],
        name: str,
        bound: dict[int, ReadConvention] | None = None,
    ) -> pa.Table:
        """Fill canonical table `name` from `raw_tables`."""
        try:
            return read_canonical(
                raw_tables, self.bundles, self.schema, name, bound
            )
        except pa.ArrowInvalid as error:
            raise ValueError(
                f"{self.raw.path}: canonical table '{name}' holds a value "
                f"that does not parse: {error}"
            ) from error

    def bound(
        self, name: str, raw: RawSchema, at: int
    ) -> dict[int, ReadConvention]:
        """Bind the conventions of `name` to the whole raw table `at`."""
        chunks = partial(_block_tables, self.raw, at, self.rows)
        return in_context(raw, self.bundles, self.schema[name], chunks)

    def built(
        self, name: str, raw: RawSchema, at: int, columns: Set[str] | None
    ) -> pa.Table:
        """Build a table others point at a chunk at a time, keyed all along."""
        bound = self.bound(name, raw, at)
        pieces = (
            self.filled([piece], name, bound)
            for piece in block_chunks(self.raw, self.rows, at, columns)
        )
        return reduce(
            lambda whole, piece: keyed(
                pa.concat_tables([whole, piece]), self.schema, name
            ),
            pieces,
        )


def block_chunks(
    raw: RawResult, size: int, at: int, columns: Set[str] | None
) -> Iterator[RawTable]:
    """Yield raw table `at` a chunk at a time, reading no block after it."""
    chunks = takewhile(
        lambda chunk: chunk[0] <= at, raw._chunks(size, columns)
    )
    yield from (chunk for ordinal, chunk in chunks if ordinal == at)


def _block_tables(
    raw: RawResult, at: int, size: int, columns: tuple[str, ...]
) -> Iterator[pa.Table]:
    yield from (
        chunk.table for chunk in block_chunks(raw, size, at, set(columns))
    )


def narrowed(raw: RawSchema, columns: Set[str]) -> RawSchema:
    """Return `raw` with only the columns `columns` names."""
    kept = tuple(name for name in raw.column_names if name in columns)
    return RawSchema(raw.table_name, kept)


def narrowed_all(
    found: tuple[RawSchema, ...], columns: Set[str] | None
) -> tuple[RawSchema, ...]:
    """Return every schema of `found` narrowed to `columns`, if any."""
    if columns is None:
        return found
    return tuple(narrowed(raw, columns) for raw in found)
