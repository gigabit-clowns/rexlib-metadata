"""Read CryoEM metadata files as pandas or polars DataFrames."""

from rexlib_metadata._rexlib import version as _version
from rexlib_metadata.registry import global_registry
from rexlib_metadata.result import ReadResult

__version__: str = _version()


def read(path: str, **kwargs) -> ReadResult:
    """Return a lazy result over the metadata file at `path`.

    The reader is chosen by the file's extension, and no row is read until
    the result is materialised.
    """
    return global_registry.read(path, **kwargs)


__all__ = ["ReadResult", "__version__", "read"]
