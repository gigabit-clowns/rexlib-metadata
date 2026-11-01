# SPDX-License-Identifier: LGPL-2.1-or-later

"""Reading and writing SQLite files, as tables and nothing more."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa

from rexlib_metadata.abc import Reader, Writer
from rexlib_metadata.convention import RawTable

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence, Set

_TABLES = (
    "SELECT name FROM sqlite_master "
    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
)


class SqliteReader(Reader):
    """Reads every table of an SQLite file, typed as the file declares."""

    def read_tables(self, path: str) -> list[RawTable]:
        """Read every table of the file at `path`, in the order made."""
        return self._read(path, None)

    def read_tables_keeping(
        self, path: str, columns: Set[str]
    ) -> list[RawTable]:
        """Read every table, selecting only what it has of `columns`."""
        return self._read(path, columns)

    def read_chunks(
        self, path: str, size: int, columns: Set[str] | None = None
    ) -> Iterator[tuple[int, RawTable]]:
        """Read every table `size` rows at a time, from one cursor each."""
        with closing(_open(path)) as connection:
            for ordinal, name in enumerate(_table_names(connection)):
                declared = _declared(connection, name, columns)
                cursor = connection.execute(_select(name, declared))
                for rows in _batches(cursor, size):
                    yield ordinal, _raw_table(name, declared, rows)

    def _read(self, path: str, columns: Set[str] | None) -> list[RawTable]:
        with closing(_open(path)) as connection:
            return [
                _whole_table(connection, name, columns)
                for name in _table_names(connection)
            ]


class SqliteWriter(Writer):
    """Writes one SQLite table per raw table, typed as Arrow holds it."""

    def write_tables(self, path: str, tables: Iterable[RawTable]) -> None:
        """Write `tables` to a new file at `path`, replacing what was there."""
        tables = list(tables)
        names = [table.schema.table_name for table in tables]
        if len(set(names)) != len(names):
            raise ValueError(
                "Two tables share a name, and an SQLite file has one table "
                "per name"
            )
        for table in tables:
            _create_statement(table)
        Path(path).write_bytes(b"")
        with closing(sqlite3.connect(path)) as connection, connection:
            for table in tables:
                _write_table(connection, table)


def _open(path: str) -> sqlite3.Connection:
    location = Path(path)
    if not location.is_file():
        raise FileNotFoundError(f"No such file: {path!r}")
    connection = sqlite3.connect(
        f"{location.resolve().as_uri()}?mode=ro", uri=True
    )
    try:
        connection.execute(_TABLES)
    except sqlite3.DatabaseError as error:
        connection.close()
        raise ValueError(f"{path} is not an SQLite file: {error}") from None
    return connection


def _whole_table(
    connection: sqlite3.Connection, name: str, columns: Set[str] | None
) -> RawTable:
    declared = _declared(connection, name, columns)
    rows = connection.execute(_select(name, declared)).fetchall()
    return _raw_table(name, declared, rows)


def _table_names(connection: sqlite3.Connection) -> list[str]:
    return [name for (name,) in connection.execute(_TABLES)]


def _declared(
    connection: sqlite3.Connection, table: str, columns: Set[str] | None
) -> list[tuple[str, pa.DataType]]:
    info = connection.execute(f"PRAGMA table_info({_quoted(table)})")
    return [
        (name, _arrow_type(kind))
        for _, name, kind, *_ in info
        if columns is None or name in columns
    ]


def _arrow_type(declared: str) -> pa.DataType:
    """Map a declared type to Arrow by SQLite's own affinity rules.

    INTEGER, TEXT, REAL and BLOB are what the file says. NUMERIC, and a
    column declaring nothing, may hold anything, so they are text, as a
    format that states no type is.
    """
    kind = declared.upper()
    if "INT" in kind:
        return pa.int64()
    if any(word in kind for word in ("CHAR", "CLOB", "TEXT")):
        return pa.string()
    if "BLOB" in kind:
        return pa.binary()
    if any(word in kind for word in ("REAL", "FLOA", "DOUB")):
        return pa.float64()
    return pa.string()


def _select(table: str, declared: Sequence[tuple[str, pa.DataType]]) -> str:
    names = ", ".join(_quoted(name) for name, _ in declared) or "NULL"
    return f"SELECT {names} FROM {_quoted(table)}"


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _batches(cursor: sqlite3.Cursor, size: int) -> Iterator[list[tuple]]:
    rows = cursor.fetchmany(size)
    yield rows
    while len(rows) == size:
        rows = cursor.fetchmany(size)
        if rows:
            yield rows


def _raw_table(
    name: str,
    declared: Sequence[tuple[str, pa.DataType]],
    rows: list[tuple],
) -> RawTable:
    if not declared:
        counted = pa.table({"_": pa.nulls(len(rows))}).drop_columns(["_"])
        return RawTable.of(name, counted)
    values = list(zip(*rows, strict=True)) if rows else [()] * len(declared)
    arrays = [
        _array(name, column, kind, column_values)
        for (column, kind), column_values in zip(declared, values, strict=True)
    ]
    schema = pa.schema([(column, kind) for column, kind in declared])
    return RawTable.of(name, pa.Table.from_arrays(arrays, schema=schema))


def _array(
    table: str, column: str, kind: pa.DataType, values: Sequence[object]
) -> pa.Array:
    if pa.types.is_string(kind):
        values = [_as_text(table, column, value) for value in values]
    try:
        return pa.array(values, type=kind)
    except (pa.ArrowInvalid, pa.ArrowTypeError, OverflowError):
        raise ValueError(
            f"Column '{column}' of table '{table}' holds a value its declared "
            f"type, {kind}, cannot hold"
        ) from None


def _as_text(table: str, column: str, value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    raise ValueError(
        f"Column '{column}' of table '{table}' declares text and holds bytes"
    )


def _create_statement(table: RawTable) -> str:
    if not table.table.num_columns:
        raise ValueError(
            f"Table '{table.schema.table_name}' has no columns, and an SQLite "
            "table needs one"
        )
    columns = ", ".join(
        f"{_quoted(field.name)} {_sqlite_type(table, field)}"
        for field in table.table.schema
    )
    return f"CREATE TABLE {_quoted(table.schema.table_name)} ({columns})"


def _sqlite_type(table: RawTable, field: pa.Field) -> str:
    kind = field.type
    if pa.types.is_integer(kind) or pa.types.is_boolean(kind):
        return "INTEGER"
    if pa.types.is_floating(kind):
        return "REAL"
    if pa.types.is_string(kind) or pa.types.is_large_string(kind):
        return "TEXT"
    if pa.types.is_binary(kind) or pa.types.is_large_binary(kind):
        return "BLOB"
    raise ValueError(
        f"Column '{field.name}' of table '{table.schema.table_name}' is "
        f"{kind}, which SQLite has no column type for"
    )


def _write_table(connection: sqlite3.Connection, table: RawTable) -> None:
    connection.execute(_create_statement(table))
    marks = ", ".join("?" * table.table.num_columns)
    name = _quoted(table.schema.table_name)
    insert = f"INSERT INTO {name} VALUES ({marks})"
    for batch in table.table.to_batches():
        columns = [column.to_pylist() for column in batch.columns]
        connection.executemany(insert, zip(*columns, strict=True))
