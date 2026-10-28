# SPDX-License-Identifier: LGPL-2.1-or-later

"""The boundary with the compiled module, where Arrow crosses over."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pyarrow as pa


@runtime_checkable
class ArrowArrayExportable(Protocol):
    """An object that hands an array over through the Arrow C interface."""

    def __arrow_c_array__(
        self, requested_schema: object | None = None
    ) -> tuple[object, object]: ...


def to_pyarrow_table(obj: ArrowArrayExportable) -> pa.Table:
    """Return what a Rust entry point handed back as a pyarrow table."""
    return pa.Table.from_batches([pa.record_batch(obj)])


def to_record_batch(table: pa.Table) -> pa.RecordBatch:
    """Return `table` as the single batch a Rust entry point takes."""
    batches = table.combine_chunks().to_batches()
    if batches:
        return batches[0]
    return pa.RecordBatch.from_pylist([], schema=table.schema)
