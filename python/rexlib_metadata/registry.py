from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rexlib_metadata.abc import Reader
    from rexlib_metadata.result import ReadResult


class MetadataRegistry:
    def __init__(self) -> None:
        self._readers: dict[str, type[Reader]] = {}

    def register_reader(self, extensions: list[str], cls: type[Reader]) -> None:
        for ext in extensions:
            self._readers[ext.lower()] = cls

    def reader_for(self, path: str) -> Reader:
        ext = Path(path).suffix.lower()
        cls = self._readers.get(ext)
        if cls is None:
            raise ValueError(f"No reader registered for '{ext}' (path: {path!r})")
        return cls()

    def read(self, path: str, **kwargs) -> ReadResult:
        return self.reader_for(path).read(path, **kwargs)


global_registry = MetadataRegistry()

# Imported after global_registry to avoid circular imports
from rexlib_metadata.conventions.star import StarReader  # noqa: E402
global_registry.register_reader([".star"], StarReader)
