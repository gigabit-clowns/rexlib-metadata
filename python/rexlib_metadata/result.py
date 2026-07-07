from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd
    import polars as pl
    import pyarrow as pa

    from rexlib_metadata.abc import Reader


class ReadResult:
    def __init__(self, path: str, reader: Reader) -> None:
        self._path = path
        self._reader = reader
        self._table: pa.Table | None = None

    def _materialize(self) -> pa.Table:
        if self._table is None:
            self._table = self._reader.read_all(self._path)
        return self._table

    def to_pandas(self) -> pd.DataFrame:
        return self._materialize().to_pandas()

    def to_polars(self) -> pl.DataFrame:
        import polars as pl
        return pl.from_arrow(self._materialize())
