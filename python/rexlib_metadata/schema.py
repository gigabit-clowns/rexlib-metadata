# SPDX-License-Identifier: LGPL-2.1-or-later

"""The canonical column structure, which knows no file format."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import pyarrow as pa


@dataclass(frozen=True)
class ColumnDescriptor:
    """One canonical column: what it is called, holds and means."""

    name: str
    dtype: pa.DataType
    unit: str | None = None
    required: bool = False
    default: object = None

    def __post_init__(self) -> None:
        """Reject a column that is required and defaulted at once."""
        if self.required and self.default is not None:
            raise ValueError(
                f"Column '{self.name}' is required and has a default; "
                "a default is what makes a column optional"
            )


@dataclass(frozen=True)
class SchemaTrait:
    """A named group of columns that belong together."""

    name: str
    columns: tuple[ColumnDescriptor, ...] = ()


Part = SchemaTrait | ColumnDescriptor


def _columns_of(part: Part) -> tuple[ColumnDescriptor, ...]:
    if isinstance(part, ColumnDescriptor):
        return (part,)
    return part.columns


class TableSchema:
    """The full column set of one canonical table."""

    def __init__(self, name: str, *parts: Part) -> None:
        """Compose a table out of traits and columns, in the order given."""
        self.name = name
        self._columns: dict[str, ColumnDescriptor] = {}
        for part in parts:
            for column in _columns_of(part):
                self._add(column)

    def _add(self, column: ColumnDescriptor) -> None:
        seen = self._columns.get(column.name)
        if seen is None:
            self._columns[column.name] = column
        elif seen != column:
            raise ValueError(
                f"Column '{column.name}' is declared twice in table "
                f"'{self.name}', and the two declarations disagree: "
                f"{seen} and {column}"
            )

    @property
    def columns(self) -> tuple[ColumnDescriptor, ...]:
        """Every column, in the order it was composed."""
        return tuple(self._columns.values())

    @property
    def required_columns(self) -> tuple[ColumnDescriptor, ...]:
        """The columns a read has to produce or fail."""
        return tuple(c for c in self._columns.values() if c.required)

    def column(self, name: str) -> ColumnDescriptor:
        """Return the column called `name`, or raise if the table has none."""
        try:
            return self._columns[name]
        except KeyError:
            raise KeyError(
                f"Table '{self.name}' has no column '{name}'"
            ) from None

    def __contains__(self, name: object) -> bool:
        """Say whether the table declares a column of that name."""
        return name in self._columns

    def __len__(self) -> int:
        """Return how many columns the table holds."""
        return len(self._columns)

    def __iter__(self) -> Iterator[ColumnDescriptor]:
        """Iterate the columns in the order they were composed."""
        return iter(self._columns.values())

    def __repr__(self) -> str:
        """Name the table and how many columns it carries."""
        return f"TableSchema({self.name!r}, {len(self)} columns)"


@dataclass(frozen=True)
class Relation:
    """Each row of `table` points, by `key`, at one row of `related`."""

    table: str
    related: str
    key: str


class Schema:
    """One or more canonical tables, as a multi-table file produces."""

    def __init__(
        self, *tables: TableSchema, relations: Iterable[Relation] = ()
    ) -> None:
        """Hold the tables given, which may not repeat a name.

        Each relation names two of them, both declaring its key and no
        other column in common, so joining one into the other loses
        nothing.
        """
        self._tables: dict[str, TableSchema] = {}
        for table in tables:
            if table.name in self._tables:
                raise ValueError(f"Table '{table.name}' is declared twice")
            self._tables[table.name] = table
        self._relations = tuple(relations)
        for relation in self._relations:
            self._check(relation)

    def relations_of(self, name: str) -> tuple[Relation, ...]:
        """Return the relations by which table `name` points at another."""
        return tuple(r for r in self._relations if r.table == name)

    def related_to(self, name: str) -> tuple[Relation, ...]:
        """Return the relations by which another table points at `name`."""
        return tuple(r for r in self._relations if r.related == name)

    def _check(self, relation: Relation) -> None:
        table = self[relation.table]
        related = self[relation.related]
        if relation.key not in table or relation.key not in related:
            raise ValueError(
                f"{relation} joins on '{relation.key}', which both tables "
                "have to declare"
            )
        shared = {c.name for c in table.columns} & {
            c.name for c in related.columns
        }
        if shared != {relation.key}:
            raise ValueError(
                f"{relation} would join two tables that also share "
                f"{', '.join(repr(n) for n in sorted(shared - {relation.key}))}"
            )

    def __getitem__(self, name: str) -> TableSchema:
        """Return the table called `name`, or raise if there is none."""
        try:
            return self._tables[name]
        except KeyError:
            raise KeyError(f"No table '{name}' in this schema") from None

    def __contains__(self, name: object) -> bool:
        """Say whether the schema declares a table of that name."""
        return name in self._tables

    def __len__(self) -> int:
        """Return how many tables the schema holds."""
        return len(self._tables)

    def __iter__(self) -> Iterator[TableSchema]:
        """Iterate the tables in the order they were given."""
        return iter(self._tables.values())

    def __repr__(self) -> str:
        """Name the tables the schema holds."""
        return f"Schema({', '.join(repr(t.name) for t in self)})"
