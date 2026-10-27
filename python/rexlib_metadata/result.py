"""What a read hands back, and the frames it turns into."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd
    import polars as pl
    import pyarrow as pa

    from rexlib_metadata.abc import Reader
    from rexlib_metadata.convention import RawTable


class ReadResult:
    """A file waiting to be read, and the tables once it has been."""

    def __init__(self, path: str, reader: Reader) -> None:
        """Hold `path` and the `reader` that will read it, opening nothing."""
        self._path = path
        self._reader = reader
        self._tables: tuple[RawTable, ...] | None = None

    @property
    def names(self) -> tuple[str, ...]:
        """Read the file, if it has not been read, and name its tables."""
        return tuple(table.schema.table_name for table in self._materialize())

    def __getitem__(self, name: str) -> ReadResult:
        """Return a result over the one table called `name`."""
        for table in self._materialize():
            if table.schema.table_name == name:
                return self._holding((table,))
        raise KeyError(
            f"{self._path} holds no table '{name}'; it holds "
            f"{', '.join(repr(n) for n in self.names)}"
        )

    def to_pandas(self) -> pd.DataFrame:
        """Read the file, if it has not been read, and return it as pandas."""
        return self._one().to_pandas()

    def to_polars(self) -> pl.DataFrame:
        """Read the file, if it has not been read, and return it as polars."""
        import polars as pl  # noqa: PLC0415

        return pl.from_arrow(self._one())

    def _materialize(self) -> tuple[RawTable, ...]:
        if self._tables is None:
            self._tables = tuple(self._reader.read_tables(self._path))
        return self._tables

    def _one(self) -> pa.Table:
        tables = self._materialize()
        if len(tables) != 1:
            raise ValueError(
                f"{self._path} holds {len(tables)} tables, "
                f"{', '.join(repr(n) for n in self.names)}; name the one you "
                "mean, as result[name]"
            )
        return tables[0].table

    def _holding(self, tables: tuple[RawTable, ...]) -> ReadResult:
        result = ReadResult(self._path, self._reader)
        result._tables = tables
        return result
