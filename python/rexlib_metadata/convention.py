"""The convention layer: file columns in, canonical columns out."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pyarrow as pa


@dataclass(frozen=True)
class RawSchema:
    """One table's shape, as the file declares it."""

    table_name: str
    column_names: tuple[str, ...]

    def has(self, *names: str) -> bool:
        """Say whether the table declares every one of `names`."""
        return all(name in self.column_names for name in names)


class ReadConvention(ABC):
    """Turns the columns of one file format into canonical ones."""

    source_columns: tuple[str, ...] = ()
    target_columns: tuple[str, ...] = ()

    @abstractmethod
    def matches(self, raw: RawSchema) -> bool:
        """Say whether this convention applies to a raw table."""

    @abstractmethod
    def load(self, table: pa.Table) -> dict[str, pa.Array]:
        """Return the canonical columns, keyed by canonical name."""


class WriteConvention(ABC):
    """Turns canonical columns into the columns of one file format."""

    source_columns: tuple[str, ...] = ()
    target_columns: tuple[str, ...] = ()

    @abstractmethod
    def store(self, canonical: dict[str, pa.Array]) -> dict[str, pa.Array]:
        """Return the file columns, keyed by the name the file uses."""


Convention = ReadConvention | WriteConvention


class ConventionBundle:
    """Every convention of one format, with read and write kept apart."""

    def __init__(
        self,
        name: str,
        read_conventions: Iterable[ReadConvention] = (),
        write_conventions: Iterable[WriteConvention] = (),
    ) -> None:
        """Hold the conventions of `name`, rejecting an ambiguous set."""
        self.name = name
        self.read_conventions = tuple(read_conventions)
        self.write_conventions = tuple(write_conventions)
        self._reject_silent(self.read_conventions)
        self._reject_silent(self.write_conventions)
        self._reject_overlap(self.read_conventions, "canonical column")
        self._reject_overlap(self.write_conventions, "file column")

    def _reject_silent(self, conventions: tuple[Convention, ...]) -> None:
        for convention in conventions:
            if not convention.target_columns:
                raise ValueError(
                    f"{type(convention).__name__} in bundle "
                    f"'{self.name}' declares no target_columns, so nothing "
                    "would ever ask for it"
                )

    def _reject_overlap(
        self, conventions: tuple[Convention, ...], what: str
    ) -> None:
        owner: dict[str, Convention] = {}
        for convention in conventions:
            for column in convention.target_columns:
                first = owner.get(column)
                if first is not None:
                    raise ValueError(
                        f"Bundle '{self.name}' produces the {what} "
                        f"'{column}' twice, from "
                        f"{type(first).__name__} and from "
                        f"{type(convention).__name__}; which one wins would "
                        "be nobody's decision"
                    )
                owner[column] = convention

    def __repr__(self) -> str:
        """Name the bundle and how many conventions it holds each way."""
        return (
            f"ConventionBundle({self.name!r}, "
            f"{len(self.read_conventions)} read, "
            f"{len(self.write_conventions)} write)"
        )
