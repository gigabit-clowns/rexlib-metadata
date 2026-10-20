"""Which reader and which conventions answer for which file."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from rexlib_metadata.abc import Reader
    from rexlib_metadata.convention import ConventionBundle
    from rexlib_metadata.result import ReadResult


class MetadataRegistry:
    """Holds the readers and the convention bundles, keyed by extension."""

    def __init__(self) -> None:
        """Start with nothing registered."""
        self._readers: dict[str, Reader] = {}
        self._bundles: dict[str, list[ConventionBundle]] = {}

    def register_reader(
        self, extensions: Iterable[str], reader: Reader
    ) -> None:
        """Register `reader` as the reader of every one of `extensions`."""
        for ext in extensions:
            self._readers[ext.lower()] = reader

    def register_bundle(
        self,
        extensions: Iterable[str],
        bundle: ConventionBundle,
        *,
        prepend: bool = False,
    ) -> None:
        """Register `bundle` for `extensions`, last in line unless prepended.

        Order is priority: the first bundle to produce a canonical column
        owns it, and a later one cannot take it back.
        """
        for ext in extensions:
            registered = self._bundles.setdefault(ext.lower(), [])
            if prepend:
                registered.insert(0, bundle)
            else:
                registered.append(bundle)

    def reader_for(self, path: str) -> Reader:
        """Return a reader for `path`, or raise if its extension has none."""
        ext = _extension(path)
        reader = self._readers.get(ext)
        if reader is None:
            raise ValueError(
                f"No reader registered for '{ext}' (path: {path!r})"
            )
        return reader

    def bundles_for(self, path: str) -> tuple[ConventionBundle, ...]:
        """Return the bundles of `path`, highest priority first."""
        return tuple(self._bundles.get(_extension(path), ()))

    def read(self, path: str) -> ReadResult:
        """Return a lazy result over `path`, through its own reader."""
        return self.reader_for(path).read(path)


def _extension(path: str) -> str:
    return Path(path).suffix.lower()


global_registry = MetadataRegistry()
