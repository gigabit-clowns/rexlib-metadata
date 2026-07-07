from __future__ import annotations

import pyarrow as pa

from rexlib_metadata._rexlib import _star_read
from rexlib_metadata.abc import Convention, Reader
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
        return result
    if hasattr(obj, '__arrow_c_stream__'):
        return pa.RecordBatchReader.from_stream(obj).read_all()
    if hasattr(obj, '__arrow_c_array__'):
        batch = pa.record_batch(obj)
        return pa.Table.from_batches([batch])
    raise TypeError(f"Cannot convert {type(obj).__name__} to pyarrow.Table")


class GenericStarConvention(Convention):
    """Passthrough: no column renaming or type conversion."""

    def matches(self, raw_schema: tuple[str, list[str]]) -> bool:
        return False

    def apply(self, batch: pa.Table) -> pa.Table:
        return batch

    def to_file_name(self, canonical_name: str) -> str:
        return canonical_name

    def to_canonical_name(self, file_name: str) -> str:
        return file_name


class StarReader(Reader):
    def read_all(self, path: str) -> pa.Table:
        return _to_pyarrow_table(_star_read(path))

    def read(self, path: str, **kwargs) -> ReadResult:
        return ReadResult(path, self)
