# SPDX-License-Identifier: LGPL-2.1-or-later

"""The boundary with the compiled module, where Arrow crosses over."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

import pyarrow as pa


@runtime_checkable
class ArrowArrayExportable(Protocol):
    """An object that hands an array over through the Arrow C interface."""

    def __arrow_c_array__(
        self, requested_schema: object | None = None
    ) -> tuple[object, object]: ...


def to_pyarrow_table(batches: Iterable[ArrowArrayExportable]) -> pa.Table:
    """Return the batches a Rust entry point handed back as one table."""
    return pa.Table.from_batches([pa.record_batch(batch) for batch in batches])


def to_record_batches(table: pa.Table) -> list[pa.RecordBatch]:
    """Return `table` as the batches a Rust entry point takes, at least one.

    The batches are the table's own, never combined: a column past 2 GiB of
    text is held in several, and one batch could not hold it.
    """
    batches = table.to_batches()
    if batches:
        return batches
    return [pa.RecordBatch.from_pylist([], schema=table.schema)]
