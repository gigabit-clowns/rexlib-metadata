# SPDX-License-Identifier: LGPL-2.1-or-later

"""Read CryoEM metadata files as pandas or polars DataFrames."""

from __future__ import annotations

from rexlib_metadata._rexlib import version as _version
from rexlib_metadata.convention import ConventionBundle
from rexlib_metadata.conventions.relion import relion4_bundle
from rexlib_metadata.conventions.star import StarReader
from rexlib_metadata.registry import global_registry
from rexlib_metadata.result import RawResult, ReadResult

__version__: str = _version()

global_registry.register_reader([".star"], StarReader())
global_registry.register_bundle([".star"], relion4_bundle())


def read(path: str, *, bundle: ConventionBundle | None = None) -> ReadResult:
    """Return a lazy canonical result over the metadata file at `path`.

    The reader and the conventions are chosen by the file's extension, and
    no row is read until the result is materialised. The columns come back
    under their canonical names; `result.raw` is the same file read as it
    names its own. Passing `bundle` uses that one instead of the registered
    ones.
    """
    return global_registry.read(path, bundle=bundle)


__all__ = ["RawResult", "ReadResult", "__version__", "read"]
