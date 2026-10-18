"""Reading STAR files, and the conventions that come with them."""

from __future__ import annotations

import pyarrow as pa

from rexlib_metadata._rexlib import _star_read
from rexlib_metadata.abc import Reader
from rexlib_metadata.result import ReadResult


def _to_pyarrow_table(obj) -> pa.Table:
    if isinstance(obj, pa.Table):
        return obj
    if isinstance(obj, pa.RecordBatch):
        return pa.Table.from_batches([obj])
    if hasattr(obj, 'to_pyarrow'):
        result = obj.to_pyarrow()
        if isinstance(result, pa.RecordBatch):
            return pa.Table.from_batches([result])
        if isinstance(result, pa.Table):
            return result
        raise TypeError(f"to_pyarrow() returned {type(result).__name__}, expected pa.Table or pa.RecordBatch")
    if hasattr(obj, '__arrow_c_stream__'):
        return pa.RecordBatchReader.from_stream(obj).read_all()
    if hasattr(obj, '__arrow_c_array__'):
        return pa.Table.from_batches([pa.record_batch(obj)])
    raise TypeError(f"Cannot convert {type(obj).__name__} to pyarrow.Table")


class StarReader(Reader):
    """Reads a STAR file through the Rust parser."""

    def read_all(self, path: str) -> pa.Table:
        """Read every row of the file at `path` into one table."""
        return _to_pyarrow_table(_star_read(path))

    def read(self, path: str, **kwargs) -> ReadResult:
        """Return a lazy result over `path`, reading no row yet."""
        return ReadResult(path, self)
