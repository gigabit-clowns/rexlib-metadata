# SPDX-License-Identifier: LGPL-2.1-or-later

"""Read CryoEM metadata files as pandas or polars DataFrames."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from rexlib_metadata._rexlib import version as _version
from rexlib_metadata.abc import Reader, Writer
from rexlib_metadata.convention import ConventionBundle
from rexlib_metadata.conventions.hdf5 import Hdf5Reader, Hdf5Writer
from rexlib_metadata.conventions.relion import relion4_bundle
from rexlib_metadata.conventions.sqlite import SqliteReader, SqliteWriter
from rexlib_metadata.conventions.star import StarReader, StarWriter
from rexlib_metadata.conventions.xmipp import HEADER, xmipp_bundle
from rexlib_metadata.registry import global_registry
from rexlib_metadata.result import Chunk, RawResult, ReadResult

if TYPE_CHECKING:
    import pandas as pd
    import polars as pl
    import pyarrow as pa

__version__: str = _version()

_STAR = (".star",)
_XMD = (".xmd",)
_SQLITE = (".sqlite", ".db")
_HDF5 = (".h5", ".hdf5")

global_registry.register_reader(_STAR, StarReader())
global_registry.register_writer(_STAR, StarWriter())
global_registry.register_bundle(_STAR, relion4_bundle())
global_registry.register_reader(_XMD, StarReader())
global_registry.register_writer(_XMD, StarWriter(header=HEADER))
global_registry.register_bundle(_XMD, xmipp_bundle())
global_registry.register_reader(_SQLITE, SqliteReader())
global_registry.register_writer(_SQLITE, SqliteWriter())
global_registry.register_reader(_HDF5, Hdf5Reader())
global_registry.register_writer(_HDF5, Hdf5Writer())


def read(
    path: str,
    *,
    columns: Iterable[str] | None = None,
    bundle: ConventionBundle | Iterable[ConventionBundle] | None = None,
    reader: Reader | None = None,
) -> ReadResult:
    """Return a lazy canonical result over the metadata file at `path`.

    The reader and the conventions are chosen by the file's extension, and
    no row is read until the result is materialised. The columns come back
    under their canonical names; `result.raw` is the same file read as it
    names its own. Passing `columns` shows only those canonical columns,
    and only the tables that declare one of them; a write still carries
    every other column of the file. Passing `reader` or `bundle` uses that
    instead of the registered ones, so a file whose extension says nothing
    of its dialect, or is not registered at all, can be read; `bundle` is
    one bundle or several in priority order, `[mine, relion4_bundle()]`
    putting yours in front of Relion's.
    """
    return global_registry.read(
        path, columns=columns, bundle=bundle, reader=reader
    )


def write(
    path: str,
    tables: Mapping[str, pa.Table | pd.DataFrame | pl.DataFrame],
    *,
    bundle: ConventionBundle | Iterable[ConventionBundle] | None = None,
    writer: Writer | None = None,
) -> None:
    """Write canonical tables, read from a file or built in memory, to `path`.

    `tables` maps a canonical table's name, as `"particles"`, to its rows as
    pandas, polars or Arrow. The format is the extension's, as in a read.
    """
    global_registry.write(path, tables, bundle=bundle, writer=writer)


__all__ = [
    "Chunk",
    "RawResult",
    "ReadResult",
    "__version__",
    "read",
    "write",
]
