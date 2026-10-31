# SPDX-License-Identifier: LGPL-2.1-or-later

"""The convention layer: file columns in, canonical columns out."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import TypeVar

import pyarrow as pa

ArrowColumn = pa.Array | pa.ChunkedArray


@dataclass(frozen=True)
class RawSchema:
    """One table's shape, as the file declares it.

    `table_name` is `""` for a table the file does not name.
    """

    table_name: str
    column_names: tuple[str, ...]

    def has(self, *names: str) -> bool:
        """Say whether the table declares every one of `names`."""
        return all(name in self.column_names for name in names)


@dataclass(frozen=True)
class RawTable:
    """One table as the file holds it, before any convention."""

    schema: RawSchema
    table: pa.Table

    @classmethod
    def of(cls, name: str, table: pa.Table) -> RawTable:
        """Build a raw table from an Arrow table and the name it had."""
        return cls(RawSchema(name, tuple(table.column_names)), table)


class ReadConvention(ABC):
    """Turns the columns of one file format into canonical ones."""

    source_columns: tuple[str, ...] = ()
    target_columns: tuple[str, ...] = ()

    @abstractmethod
    def matches(self, raw: RawSchema) -> bool:
        """Say whether this convention applies to a raw table."""

    @abstractmethod
    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return the canonical columns, keyed by canonical name."""


class WriteConvention(ABC):
    """Turns canonical columns into the columns of one file format."""

    source_columns: tuple[str, ...] = ()
    target_columns: tuple[str, ...] = ()

    @abstractmethod
    def store(
        self, canonical: dict[str, ArrowColumn]
    ) -> dict[str, ArrowColumn]:
        """Return the file columns, keyed by the name the file uses."""


_Convention = ReadConvention | WriteConvention
_C = TypeVar("_C", bound=_Convention)


class ConventionBundle:
    """Every convention of one format, grouped by the table it fills."""

    def __init__(
        self,
        name: str,
        read: Mapping[str, Iterable[ReadConvention]] | None = None,
        write: Mapping[str, Iterable[WriteConvention]] | None = None,
    ) -> None:
        """Hold the conventions of `name`, rejecting an ambiguous group."""
        self.name = name
        self._read = _grouped(read)
        self._write = _grouped(write)
        self._validate(self._read, "canonical column")
        self._validate(self._write, "file column")

    @property
    def tables(self) -> tuple[str, ...]:
        """Name every canonical table this bundle reads into."""
        return tuple(self._read)

    def read_conventions(self, table: str) -> tuple[ReadConvention, ...]:
        """Return the conventions that fill canonical table `table`."""
        return self._read.get(table, ())

    def write_conventions(self, table: str) -> tuple[WriteConvention, ...]:
        """Return the conventions that write canonical table `table`."""
        return self._write.get(table, ())

    def _validate(
        self, groups: Mapping[str, tuple[_Convention, ...]], what: str
    ) -> None:
        for table, conventions in groups.items():
            self._reject_silent(conventions)
            self._reject_overlap(table, conventions, what)

    def _reject_silent(self, conventions: tuple[_Convention, ...]) -> None:
        for convention in conventions:
            if not convention.target_columns:
                raise ValueError(
                    f"{type(convention).__name__} in bundle "
                    f"'{self.name}' declares no target_columns, so nothing "
                    "would ever ask for it"
                )

    def _reject_overlap(
        self, table: str, conventions: tuple[_Convention, ...], what: str
    ) -> None:
        owner: dict[str, _Convention] = {}
        for column, convention in _declarations(conventions):
            first = owner.setdefault(column, convention)
            if first is not convention:
                raise ValueError(
                    f"Bundle '{self.name}' produces the {what} '{column}' "
                    f"twice for table '{table}', from "
                    f"{type(first).__name__} and from "
                    f"{type(convention).__name__}; which one wins would be "
                    "nobody's decision"
                )

    def __repr__(self) -> str:
        """Name the bundle and the tables it reads into."""
        return f"ConventionBundle({self.name!r}, {list(self._read)})"


def _grouped(
    groups: Mapping[str, Iterable[_C]] | None,
) -> dict[str, tuple[_C, ...]]:
    if groups is None:
        return {}
    return {table: tuple(group) for table, group in groups.items()}


def _declarations(
    conventions: tuple[_Convention, ...],
) -> Iterator[tuple[str, _Convention]]:
    return (
        (column, convention)
        for convention in conventions
        for column in convention.target_columns
    )
