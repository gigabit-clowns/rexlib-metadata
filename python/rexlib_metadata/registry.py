# SPDX-License-Identifier: LGPL-2.1-or-later

"""Which reader and which conventions answer for which file."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rexlib_metadata.canonical import SCHEMA
from rexlib_metadata.convention import as_bundles
from rexlib_metadata.result import RawResult, ReadResult
from rexlib_metadata.writing import canonical_frame, replaced, written_frames

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from rexlib_metadata._arrow import Frame
    from rexlib_metadata.abc import Reader, Writer
    from rexlib_metadata.convention import ConventionBundle
    from rexlib_metadata.schema import Schema


class MetadataRegistry:
    """Holds the readers and the convention bundles, keyed by extension."""

    def __init__(self, schema: Schema = SCHEMA) -> None:
        """Start with nothing registered, filling `schema` when read."""
        self._schema = schema
        self._readers: dict[str, Reader] = {}
        self._writers: dict[str, Writer] = {}
        self._bundles: dict[str, list[ConventionBundle]] = {}

    def register_reader(
        self, extensions: str | Iterable[str], reader: Reader
    ) -> None:
        """Register `reader` as the reader of `extensions`, or of one."""
        for ext in _as_extensions(extensions):
            self._readers[ext] = reader

    def register_writer(
        self, extensions: str | Iterable[str], writer: Writer
    ) -> None:
        """Register `writer` as the writer of `extensions`, or of one."""
        for ext in _as_extensions(extensions):
            self._writers[ext] = writer

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

    def writer_for(self, path: str) -> Writer:
        """Return a writer for `path`, or raise if its extension has none."""
        ext = _extension(path)
        writer = self._writers.get(ext)
        if writer is None:
            raise ValueError(
                f"No writer registered for '{ext}' (path: {path!r})"
            )
        return writer

    def bundles_for(self, path: str) -> tuple[ConventionBundle, ...]:
        """Return the bundles of `path`, highest priority first."""
        return tuple(self._bundles.get(_extension(path), ()))

    def read(
        self,
        path: str,
        *,
        columns: Iterable[str] | None = None,
        bundle: ConventionBundle | Iterable[ConventionBundle] | None = None,
        reader: Reader | None = None,
    ) -> ReadResult:
        """Return a lazy canonical result over `path`, through its reader.

        The reader and the bundles registered for the extension apply, the
        bundles in their order, unless `reader` or `bundle` names what to
        use instead, `bundle` being one bundle or several in priority
        order; the extension need not be registered when both are named.
        `columns` narrows the result to those canonical columns.
        """
        bundles = as_bundles(bundle)
        if bundles is None:
            bundles = self.bundles_for(path)
        if reader is None:
            reader = self.reader_for(path)
        raw = RawResult(path, reader, self)
        return ReadResult(raw, bundles, self._schema, columns=columns)


    def write(
        self,
        path: str,
        tables: Mapping[str, Frame],
        *,
        bundle: ConventionBundle | Iterable[ConventionBundle] | None = None,
        writer: Writer | None = None,
    ) -> None:
        """Write canonical tables, built anywhere, to `path`.

        `tables` maps a canonical table's name to its rows, as pandas,
        polars or Arrow, every column canonical and the required ones
        there. They are spelled as the destination's conventions write
        them, a related table the format has no place for joined into the
        rows that point at it, and a column the format cannot spell left
        out. The writer and the conventions come from the extension unless
        `writer` or `bundle` names them.
        """
        bundles = as_bundles(bundle)
        if bundles is None:
            bundles = self.bundles_for(path)
        if writer is None:
            writer = self.writer_for(path)
        canonical = {
            name: canonical_frame(name, frame, self._schema)
            for name, frame in tables.items()
        }
        written = written_frames(canonical, bundles, self._schema)
        if not written:
            raise ValueError(f"Nothing would reach {path}: no table was given")
        replaced(
            path, lambda temporary: writer.write_tables(temporary, written)
        )


def _as_extensions(extensions: str | Iterable[str]) -> tuple[str, ...]:
    if isinstance(extensions, str):
        return (extensions.lower(),)
    return tuple(ext.lower() for ext in extensions)


def _extension(path: str) -> str:
    return Path(path).suffix.lower()


global_registry = MetadataRegistry()
