# SPDX-License-Identifier: LGPL-2.1-or-later

"""Joining a table into the rows that point at it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.compute as pc

if TYPE_CHECKING:
    from collections.abc import Iterable

    from rexlib_metadata.schema import Relation


def joined(table: pa.Table, related: pa.Table, key: str) -> pa.Table:
    """Append to each row of `table` the columns of the row `key` names.

    The rows of `table` keep their order, and one whose key names no row
    of `related` has nulls there. A table without the key is returned as
    it is, since it points at nothing.
    """
    if key not in table.column_names or key not in related.column_names:
        return table
    keys = related.column(key).combine_chunks()
    if len(pc.unique(keys)) != len(keys):
        raise ValueError(
            f"'{key}' repeats a value, so a row pointing at it would not "
            "know which one it means"
        )
    rows = pc.index_in(table.column(key), value_set=keys)
    picked = related.drop_columns([key]).take(rows)
    for name in picked.column_names:
        table = table.append_column(name, picked.column(name))
    return table


def joined_all(
    table: pa.Table, related: Iterable[tuple[Relation, pa.Table]]
) -> pa.Table:
    """Join each related table into `table` by its relation's key."""
    for relation, other in related:
        table = joined(table, other, relation.key)
    return table
