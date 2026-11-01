# SPDX-License-Identifier: LGPL-2.1-or-later

from collections.abc import Iterator, Sequence, Set

from rexlib_metadata._arrow import ArrowArrayExportable

def version() -> str: ...
def _star_read_tables(
    path: str, columns: Set[str] | None = None
) -> Sequence[tuple[str, Sequence[ArrowArrayExportable]]]: ...
def _star_read_headers(path: str) -> Sequence[tuple[str, Sequence[str]]]: ...
def _star_read_chunks(
    path: str, chunk_size: int, columns: Set[str] | None = None
) -> StarChunks: ...

class StarChunks(Iterator[tuple[str, int, ArrowArrayExportable]]):
    def __next__(self) -> tuple[str, int, ArrowArrayExportable]: ...

def _star_write(
    path: str,
    tables: Sequence[tuple[str, Sequence[ArrowArrayExportable]]],
    header: str | None = None,
) -> None: ...
