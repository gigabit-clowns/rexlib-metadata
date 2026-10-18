"""Which reader answers for which file."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rexlib_metadata.abc import Reader
    from rexlib_metadata.result import ReadResult


class MetadataRegistry:
    """Holds the readers, and picks one by extension."""

    def __init__(self) -> None:
        """Start with no reader registered."""
        self._readers: dict[str, type[Reader]] = {}

    def register_reader(self, extensions: list[str], cls: type[Reader]) -> None:
        """Register `cls` as the reader of every one of `extensions`."""
        for ext in extensions:
            self._readers[ext.lower()] = cls

    def reader_for(self, path: str) -> Reader:
        """Return a reader for `path`, or raise if its extension has none."""
        ext = Path(path).suffix.lower()
        cls = self._readers.get(ext)
        if cls is None:
            raise ValueError(f"No reader registered for '{ext}' (path: {path!r})")
        return cls()

    def read(self, path: str, **kwargs) -> ReadResult:
        """Return a lazy result over `path`, through the reader it belongs to."""
        return self.reader_for(path).read(path, **kwargs)


global_registry = MetadataRegistry()

from rexlib_metadata.conventions.star import StarReader  # noqa: E402

global_registry.register_reader([".star"], StarReader)
