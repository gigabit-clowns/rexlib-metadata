# SPDX-License-Identifier: LGPL-2.1-or-later

"""Reading and writing HDF5 files, as tables and nothing more.

HDF5 has groups and datasets and no tables, so two layouts are read as
one: a one-dimensional compound dataset, each field a column, and a group
whose children are datasets of one length, each a column, a dataset of two
dimensions being a vector per row.
A table is named for its path in the file, without the leading slash, so
the columns at the root make the table `""`. Anything else is not a table
and is left alone. The writer writes the second layout.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.compute as pc

from rexlib_metadata.abc import Reader, Writer
from rexlib_metadata.convention import RawSchema, RawTable

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Set

    import numpy as np

_VECTOR_PER_ROW = 2


class Hdf5Reader(Reader):
    """Reads every table an HDF5 file holds, typed as the file declares."""

    def read_tables(self, path: str) -> list[RawTable]:
        """Read every table of the file at `path`, in the file's order."""
        return self._read(path, None)

    def read_schemas(self, path: str) -> list[RawSchema]:
        """Name every table and its columns, reading no dataset."""
        with _open(path) as file:
            return [
                RawSchema(table.name, table.column_names)
                for table in _tables(file)
            ]

    def read_tables_keeping(
        self, path: str, columns: Set[str]
    ) -> list[RawTable]:
        """Read every table, reading only what it has of `columns`."""
        return self._read(path, columns)

    def read_chunks(
        self, path: str, size: int, columns: Set[str] | None = None
    ) -> Iterator[tuple[int, RawTable]]:
        """Read every table `size` rows at a time, slicing its datasets."""
        with _open(path) as file:
            for ordinal, table in enumerate(_tables(file)):
                for start in _starts(table.rows, size):
                    rows = slice(start, start + size)
                    yield ordinal, table.read(rows, columns)

    def _read(self, path: str, columns: Set[str] | None) -> list[RawTable]:
        with _open(path) as file:
            return [
                table.read(slice(None), columns) for table in _tables(file)
            ]


class Hdf5Writer(Writer):
    """Writes each raw table as a group with one dataset per column."""

    def write_tables(self, path: str, tables: Iterable[RawTable]) -> None:
        """Write `tables` to a new file at `path`, replacing what was there."""
        tables = list(tables)
        _check_paths(tables)
        h5py = _h5py()
        with h5py.File(path, "w", track_order=True) as file:
            for table in tables:
                _write_table(file, table)


class _CompoundTable:
    """A one-dimensional compound dataset, each field a column."""

    def __init__(self, name: str, dataset: Any) -> None:
        self.name = name
        self.rows = len(dataset)
        self.column_names: tuple[str, ...] = dataset.dtype.names
        self._dataset = dataset

    def read(self, rows: slice, columns: Set[str] | None) -> RawTable:
        names = _kept(self.column_names, columns)
        arrays = [
            _arrow(self.name, field, self._dataset.fields(field)[rows])
            for field in names
        ]
        return RawTable.of(self.name, pa.table(arrays, names=names))


class _ColumnGroup:
    """A group whose children are datasets of one length, one per column."""

    def __init__(self, name: str, datasets: dict[str, Any]) -> None:
        self.name = name
        self.rows = len(next(iter(datasets.values())))
        self.column_names = tuple(datasets)
        self._datasets = datasets

    def read(self, rows: slice, columns: Set[str] | None) -> RawTable:
        names = _kept(self.column_names, columns)
        arrays = [
            _arrow(self.name, name, _values(self._datasets[name], rows))
            for name in names
        ]
        return RawTable.of(self.name, pa.table(arrays, names=names))


def _h5py() -> Any:
    """Import h5py, and with it NumPy, only once HDF5 is asked for."""
    try:
        return importlib.import_module("h5py")
    except ImportError:
        raise ImportError(
            "Reading or writing HDF5 needs h5py: "
            "pip install rexlib-metadata[hdf5]"
        ) from None


def _open(path: str) -> Any:
    if not Path(path).is_file():
        raise FileNotFoundError(f"No such file: {path!r}")
    h5py = _h5py()
    try:
        return h5py.File(path, "r")
    except OSError as error:
        raise ValueError(f"{path} is not an HDF5 file: {error}") from None


def _tables(group: Any) -> Iterator[_CompoundTable | _ColumnGroup]:
    """Walk `group` in the file's order, yielding what reads as a table."""
    columns = _column_datasets(group)
    if columns:
        yield _ColumnGroup(group.name.lstrip("/"), columns)
        return
    h5py = _h5py()
    for child in group.values():
        if _is_compound(child):
            yield _CompoundTable(child.name.lstrip("/"), child)
        elif isinstance(child, h5py.Group):
            yield from _tables(child)


def _column_datasets(group: Any) -> dict[str, Any]:
    children = dict(group.items())
    if not children or not all(_is_column(c) for c in children.values()):
        return {}
    if len({len(child) for child in children.values()}) != 1:
        return {}
    return children


def _is_column(item: Any) -> bool:
    return (
        isinstance(item, _h5py().Dataset)
        and item.ndim in {1, _VECTOR_PER_ROW}
        and item.dtype.names is None
    )


def _is_compound(item: Any) -> bool:
    return (
        isinstance(item, _h5py().Dataset)
        and item.ndim == 1
        and item.dtype.names is not None
    )


def _kept(names: tuple[str, ...], columns: Set[str] | None) -> list[str]:
    return [name for name in names if columns is None or name in columns]


def _values(dataset: Any, rows: slice) -> np.ndarray:
    if _h5py().check_string_dtype(dataset.dtype) is not None:
        return dataset.asstr()[rows].astype(object)
    return dataset[rows]


def _starts(rows: int, size: int) -> range:
    return range(0, rows, size) if rows else range(1)


def _arrow(table: str, column: str, values: np.ndarray) -> pa.Array:
    """Turn the NumPy values of one column into Arrow, as typed."""
    kind = values.dtype.kind
    if kind == "S":
        return pa.array([value.decode() for value in values], pa.string())
    if kind in "UO":
        return pa.array(values.tolist(), pa.string())
    if kind in "biuf":
        return _numbers(table, column, values)
    raise _untyped(table, column, values.dtype, "an Arrow type")


def _numbers(table: str, column: str, values: np.ndarray) -> pa.Array:
    if values.ndim == 1:
        return pa.array(values)
    if values.ndim == _VECTOR_PER_ROW:
        flat = pa.array(values.reshape(-1))
        return pa.FixedSizeListArray.from_arrays(flat, values.shape[1])
    raise _untyped(table, column, values.dtype, "an Arrow type")


def _untyped(table: str, column: str, kind: object, what: str) -> ValueError:
    return ValueError(
        f"Column '{column}' of table '{table}' is {kind}, which has no "
        f"{what} here"
    )


def _check_paths(tables: list[RawTable]) -> None:
    names = [table.schema.table_name for table in tables]
    _check_names(names)
    _check_columns(tables)
    _check_nesting(names)


def _check_names(names: list[str]) -> None:
    if "" in names and len(names) > 1:
        raise ValueError(
            "A table with no name is written at the root of the file, where "
            "it would hold the other tables among its columns"
        )
    if len(set(names)) != len(names):
        raise ValueError(
            "Two tables share a name, and HDF5 has one group per path"
        )


def _check_columns(tables: list[RawTable]) -> None:
    for table in tables:
        if not table.table.num_columns:
            raise ValueError(
                f"Table '{table.schema.table_name}' has no columns, and an "
                "empty group does not read back as a table"
            )


def _check_nesting(names: list[str]) -> None:
    for outer, inner in _nested(names):
        raise ValueError(
            f"Table '{inner}' would be written inside table '{outer}', "
            f"which would then read back as a group rather than a table"
        )


def _nested(names: list[str]) -> list[tuple[str, str]]:
    return [
        (outer, inner)
        for outer in names
        for inner in names
        if outer and inner.startswith(f"{outer}/")
    ]


def _write_table(file: Any, table: RawTable) -> None:
    name = table.schema.table_name
    group = file.create_group(name, track_order=True) if name else file
    for column in table.table.column_names:
        group.create_dataset(
            column, data=_numpy(name, column, table.table.column(column))
        )


def _numpy(table: str, column: str, values: pa.ChunkedArray) -> Any:
    if values.null_count:
        raise ValueError(
            f"Column '{column}' of table '{table}' holds nulls, which an "
            "HDF5 dataset cannot"
        )
    kind = values.type
    if pa.types.is_string(kind) or pa.types.is_large_string(kind):
        return values.to_numpy(zero_copy_only=False).astype(
            _h5py().string_dtype()
        )
    if pa.types.is_fixed_size_list(kind):
        flat = pc.list_flatten(values).to_numpy()
        return flat.reshape(len(values), kind.list_size)
    if _is_number(kind):
        return values.to_numpy(zero_copy_only=False)
    raise _untyped(table, column, kind, "HDF5 dataset type")


def _is_number(kind: pa.DataType) -> bool:
    return (
        pa.types.is_integer(kind)
        or pa.types.is_floating(kind)
        or pa.types.is_boolean(kind)
    )
