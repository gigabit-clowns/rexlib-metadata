"""Reading STAR files, and the conventions that come with them."""

from __future__ import annotations

from rexlib_metadata._arrow import to_pyarrow_table
from rexlib_metadata._rexlib import _star_read_tables
from rexlib_metadata.abc import Reader
from rexlib_metadata.convention import RawTable


class StarReader(Reader):
    """Reads a STAR file through the Rust parser."""

    def read_tables(self, path: str) -> list[RawTable]:
        """Read every data block of the file at `path`."""
        return [
            RawTable.of(name, to_pyarrow_table(batch))
            for name, batch in _star_read_tables(path)
        ]
