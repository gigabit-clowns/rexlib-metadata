# SPDX-License-Identifier: LGPL-2.1-or-later

"""Read CryoEM metadata files as pandas or polars DataFrames."""

from __future__ import annotations

from collections.abc import Iterable

from rexlib_metadata._rexlib import version as _version
from rexlib_metadata.abc import Reader
from rexlib_metadata.convention import ConventionBundle
from rexlib_metadata.conventions.relion import relion4_bundle
from rexlib_metadata.conventions.sqlite import SqliteReader, SqliteWriter
from rexlib_metadata.conventions.star import StarReader, StarWriter
from rexlib_metadata.conventions.xmipp import HEADER, xmipp_bundle
from rexlib_metadata.registry import global_registry
from rexlib_metadata.result import Chunk, RawResult, ReadResult

__version__: str = _version()

_STAR = (".star",)
_XMD = (".xmd",)
_SQLITE = (".sqlite", ".db")

global_registry.register_reader(_STAR, StarReader())
global_registry.register_writer(_STAR, StarWriter())
global_registry.register_bundle(_STAR, relion4_bundle())
global_registry.register_reader(_XMD, StarReader())
global_registry.register_writer(_XMD, StarWriter(header=HEADER))
global_registry.register_bundle(_XMD, xmipp_bundle())
global_registry.register_reader(_SQLITE, SqliteReader())
global_registry.register_writer(_SQLITE, SqliteWriter())


def read(
    path: str,
    *,
    columns: Iterable[str] | None = None,
    bundle: ConventionBundle | None = None,
    reader: Reader | None = None,
) -> ReadResult:
    """Return a lazy canonical result over the metadata file at `path`.

    The reader and the conventions are chosen by the file's extension, and
    no row is read until the result is materialised. The columns come back
    under their canonical names; `result.raw` is the same file read as it
    names its own. Passing `columns` shows only those canonical columns,
    and only the tables that declare one of them; a write still carries
    every other column of the file. Passing `reader` or `bundle` uses that
    one instead of the registered ones, so a file whose extension says
    nothing of its dialect, or is not registered at all, can be read.
    """
    return global_registry.read(
        path, columns=columns, bundle=bundle, reader=reader
    )


__all__ = ["Chunk", "RawResult", "ReadResult", "__version__", "read"]
