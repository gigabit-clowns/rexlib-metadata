"""Read CryoEM metadata files as pandas or polars DataFrames."""

from rexlib_metadata._rexlib import version as _version
from rexlib_metadata.conventions.star import StarReader
from rexlib_metadata.registry import global_registry
from rexlib_metadata.result import ReadResult

__version__: str = _version()

global_registry.register_reader([".star"], StarReader())


def read(path: str) -> ReadResult:
    """Return a lazy result over the metadata file at `path`.

    The reader is chosen by the file's extension, and no row is read until
    the result is materialised.
    """
    return global_registry.read(path)


__all__ = ["ReadResult", "__version__", "read"]
