"""What a read hands back, and the frames it turns into."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd
    import polars as pl
    import pyarrow as pa

    from rexlib_metadata.abc import Reader


class ReadResult:
    """A file waiting to be read, and the table once it has been."""

    def __init__(self, path: str, reader: Reader) -> None:
        """Hold `path` and the `reader` that will read it, opening nothing."""
        self._path = path
        self._reader = reader
        self._table: pa.Table | None = None

    def _materialize(self) -> pa.Table:
        if self._table is None:
            self._table = self._reader.read_all(self._path)
        return self._table

    def to_pandas(self) -> pd.DataFrame:
        """Read the file, if it has not been read, and return it as pandas."""
        return self._materialize().to_pandas()

    def to_polars(self) -> pl.DataFrame:
        """Read the file, if it has not been read, and return it as polars."""
        import polars as pl  # noqa: PLC0415

        return pl.from_arrow(self._materialize())
