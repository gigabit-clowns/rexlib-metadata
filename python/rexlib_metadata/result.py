# SPDX-License-Identifier: LGPL-2.1-or-later

"""What a read hands back: the canonical view, and the file's own."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from rexlib_metadata.engine import produced_tables, read_canonical

if TYPE_CHECKING:
    from collections.abc import Iterable

    import pandas as pd
    import polars as pl
    import pyarrow as pa

    from rexlib_metadata.abc import Reader
    from rexlib_metadata.convention import ConventionBundle, RawTable
    from rexlib_metadata.registry import MetadataRegistry
    from rexlib_metadata.schema import Schema


class RawResult:
    """A file waiting to be read, and its own tables once it has been."""

    def __init__(
        self, path: str, reader: Reader, registry: MetadataRegistry
    ) -> None:
        """Hold `path` and the `reader` that will read it, opening nothing."""
        self._path = path
        self._reader = reader
        self._registry = registry
        self._tables: tuple[RawTable, ...] | None = None

    @property
    def path(self) -> str:
        """The file this result reads."""
        return self._path

    @property
    def names(self) -> tuple[str, ...]:
        """Read the file, if it has not been read, and name its tables."""
        return tuple(table.schema.table_name for table in self.tables())

    def __getitem__(self, name: str) -> RawResult:
        """Return a result over the one table the file calls `name`."""
        for table in self.tables():
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

        return cast("pl.DataFrame", pl.from_arrow(self._one()))

    def tables(self) -> tuple[RawTable, ...]:
        """Read the file, if it has not been read, and return every table."""
        if self._tables is None:
            self._tables = tuple(self._reader.read_tables(self._path))
        return self._tables

    def write(self, path: str) -> None:
        """Write the tables this result holds to `path`, as they are.

        The writer is chosen by the destination's extension, and the names
        written are the ones the tables carry.
        """
        self._registry.writer_for(path).write_tables(path, self.tables())

    def _one(self) -> pa.Table:
        tables = self.tables()
        if len(tables) != 1:
            raise ValueError(
                f"{self._path} holds {len(tables)} tables, "
                f"{', '.join(repr(n) for n in self.names)}; name the one you "
                "mean, as result[name]"
            )
        return tables[0].table

    def _holding(self, tables: tuple[RawTable, ...]) -> RawResult:
        result = RawResult(self._path, self._reader, self._registry)
        result._tables = tables
        return result


class ReadResult:
    """A file as the canonical vocabulary names it, not as it names itself."""

    def __init__(
        self,
        raw: RawResult,
        bundles: Iterable[ConventionBundle],
        schema: Schema,
        table: str | None = None,
    ) -> None:
        """Hold the raw read, the bundles to apply and the schema to fill."""
        self._raw = raw
        self._bundles = tuple(bundles)
        self._schema = schema
        self._table = table

    @property
    def raw(self) -> RawResult:
        """The same file, read as it names its own tables and columns."""
        return self._raw

    @property
    def names(self) -> tuple[str, ...]:
        """Name the canonical tables these conventions fill from this file."""
        if self._table is not None:
            return (self._table,)
        return produced_tables(self._raw.tables(), self._bundles, self._schema)

    def __getitem__(self, name: str) -> ReadResult:
        """Return a result over the one canonical table called `name`."""
        if name not in self.names:
            raise KeyError(
                f"{self._raw.path} fills no canonical table '{name}'; it "
                f"fills {', '.join(repr(n) for n in self.names)}"
            )
        return ReadResult(self._raw, self._bundles, self._schema, name)

    def to_pandas(self) -> pd.DataFrame:
        """Read the file, if it has not been read, and return it as pandas."""
        return self._one().to_pandas()

    def to_polars(self) -> pl.DataFrame:
        """Read the file, if it has not been read, and return it as polars."""
        import polars as pl  # noqa: PLC0415

        return cast("pl.DataFrame", pl.from_arrow(self._one()))

    def _one(self) -> pa.Table:
        name = self._table if self._table is not None else self._sole_name()
        return read_canonical(
            self._raw.tables(), self._bundles, self._schema[name]
        )

    def _sole_name(self) -> str:
        names = self.names
        if len(names) == 1:
            return names[0]
        if not names:
            raise ValueError(
                f"No convention fills a canonical table from "
                f"{self._raw.path}; read the file's own columns through "
                ".raw, or pass a bundle of your own as bundle="
            )
        raise ValueError(
            f"{self._raw.path} fills {len(names)} canonical tables, "
            f"{', '.join(repr(n) for n in names)}; name the one you mean, "
            "as result[name]"
        )
