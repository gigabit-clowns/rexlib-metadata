# SPDX-License-Identifier: LGPL-2.1-or-later

"""The boundary with the compiled module, where Arrow crosses over."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import pyarrow as pa

if TYPE_CHECKING:
    from typing import TypeAlias, TypeGuard

    import pandas as pd
    import polars as pl

    Frame: TypeAlias = pa.Table | pd.DataFrame | pl.DataFrame


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


def as_arrow_table(frame: Frame) -> pa.Table:
    """Return a pandas, polars or Arrow table as an Arrow one."""
    if isinstance(frame, pa.Table):
        return frame
    if _is_polars(frame):
        return frame.to_arrow()
    if _is_pandas(frame):
        return pa.Table.from_pandas(frame, preserve_index=False)
    raise TypeError(
        f"A table is a pandas or polars DataFrame or an Arrow table, not "
        f"{type(frame).__name__}"
    )


def _is_polars(frame: object) -> TypeGuard[pl.DataFrame]:
    polars = sys.modules.get("polars")
    return polars is not None and isinstance(frame, polars.DataFrame)


def _is_pandas(frame: object) -> TypeGuard[pd.DataFrame]:
    pandas = sys.modules.get("pandas")
    return pandas is not None and isinstance(frame, pandas.DataFrame)
