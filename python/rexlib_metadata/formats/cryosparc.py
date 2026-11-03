# SPDX-License-Identifier: LGPL-2.1-or-later

"""Reading cryoSPARC's `.cs`, a NumPy structured array saved with `np.save`.

A file is one table, `""`, each field a column typed as declared. A field of
several values per row, such as `alignments3D/pose`, is a fixed-size list.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa

from rexlib_metadata.abc import Reader
from rexlib_metadata.convention import RawSchema, RawTable

if TYPE_CHECKING:
    from collections.abc import Iterator, Set

    import numpy as np


class CsReader(Reader):
    """Reads a cryoSPARC `.cs` file, mapped rather than loaded."""

    def read_tables(self, path: str) -> list[RawTable]:
        """Read every row of the file at `path`."""
        return [_table(_open(path), None)]

    def read_schemas(self, path: str) -> list[RawSchema]:
        """Name the file's fields, reading no row."""
        return [RawSchema("", _fields(_open(path)))]

    def read_tables_keeping(
        self, path: str, columns: Set[str]
    ) -> list[RawTable]:
        """Read only the fields `columns` names."""
        return [_table(_open(path), columns)]

    def read_chunks(
        self, path: str, size: int, columns: Set[str] | None = None
    ) -> Iterator[tuple[int, RawTable]]:
        """Read `size` rows at a time from the mapped file."""
        array = _open(path)
        starts = range(0, len(array), size) if len(array) else range(1)
        for start in starts:
            yield 0, _table(array[start : start + size], columns)


def _open(path: str) -> np.ndarray:
    if not Path(path).is_file():
        raise FileNotFoundError(f"No such file: {path!r}")
    try:
        import numpy as np
    except ImportError:
        raise ImportError(
            "Reading cryoSPARC's .cs needs NumPy: "
            "pip install rexlib-metadata[cryosparc]"
        ) from None
    try:
        array = np.load(path, mmap_mode="r", allow_pickle=False)
    except ValueError as error:
        raise ValueError(f"{path} is not a cryoSPARC file: {error}") from None
    if array.dtype.names is None or array.ndim != 1:
        raise ValueError(f"{path} is not a cryoSPARC file: no fields")
    return array


def _fields(array: np.ndarray) -> tuple[str, ...]:
    return tuple(array.dtype.names or ())


def _table(array: np.ndarray, columns: Set[str] | None) -> RawTable:
    names = [n for n in _fields(array) if columns is None or n in columns]
    arrays = [_arrow(name, array[name]) for name in names]
    return RawTable.of("", pa.table(arrays, names=names))


def _arrow(name: str, values: np.ndarray) -> pa.Array:
    kind = values.dtype.kind
    if kind == "S":
        return pa.array(values).cast(pa.string())
    if kind not in "biuf":
        raise ValueError(f"Field '{name}' holds {values.dtype}, not a column")
    if values.ndim == 1:
        return pa.array(values)
    flat = pa.array(values.reshape(-1))
    return pa.FixedSizeListArray.from_arrays(flat, values.shape[1])
