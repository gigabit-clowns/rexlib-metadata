# SPDX-License-Identifier: LGPL-2.1-or-later

"""Which reader and which conventions answer for which file."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rexlib_metadata.canonical import SCHEMA
from rexlib_metadata.result import ReadResult

if TYPE_CHECKING:
    from collections.abc import Iterable

    from rexlib_metadata.abc import Reader
    from rexlib_metadata.convention import ConventionBundle
    from rexlib_metadata.schema import Schema


class MetadataRegistry:
    """Holds the readers and the convention bundles, keyed by extension."""

    def __init__(self, schema: Schema = SCHEMA) -> None:
        """Start with nothing registered, filling `schema` when read."""
        self._schema = schema
        self._readers: dict[str, Reader] = {}
        self._bundles: dict[str, list[ConventionBundle]] = {}

    def register_reader(
        self, extensions: str | Iterable[str], reader: Reader
    ) -> None:
        """Register `reader` as the reader of `extensions`, or of one."""
        for ext in _as_extensions(extensions):
            self._readers[ext] = reader

    def register_bundle(
        self,
        extensions: str | Iterable[str],
        bundle: ConventionBundle,
        *,
        prepend: bool = False,
    ) -> None:
        """Register `bundle` for `extensions`, last in line unless prepended.

        Order is priority: the first bundle to produce a canonical column
        owns it, and a later one cannot take it back.
        """
        for ext in _as_extensions(extensions):
            registered = self._bundles.setdefault(ext, [])
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

    def read(
        self, path: str, *, bundle: ConventionBundle | None = None
    ) -> ReadResult:
        """Return a lazy canonical result over `path`, through its reader.

        The bundles registered for the extension apply, in their order,
        unless `bundle` names the one to use instead.
        """
        bundles = (bundle,) if bundle is not None else self.bundles_for(path)
        raw = self.reader_for(path).read(path)
        return ReadResult(raw, bundles, self._schema)


def _as_extensions(extensions: str | Iterable[str]) -> tuple[str, ...]:
    if isinstance(extensions, str):
        return (extensions.lower(),)
    return tuple(ext.lower() for ext in extensions)


def _extension(path: str) -> str:
    return Path(path).suffix.lower()


global_registry = MetadataRegistry()
