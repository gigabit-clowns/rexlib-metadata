"""Reading STAR files, and the conventions that come with them."""

from __future__ import annotations

import pyarrow as pa

from rexlib_metadata._arrow import to_pyarrow_table
from rexlib_metadata._rexlib import _star_read
from rexlib_metadata.abc import Reader
from rexlib_metadata.result import ReadResult


class StarReader(Reader):
    """Reads a STAR file through the Rust parser."""

    def read_all(self, path: str) -> pa.Table:
        """Read every row of the file at `path` into one table."""
        return to_pyarrow_table(_star_read(path))

    def read(self, path: str, **kwargs) -> ReadResult:
        """Return a lazy result over `path`, reading no row yet."""
        return ReadResult(path, self)
