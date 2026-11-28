# SPDX-License-Identifier: LGPL-2.1-or-later

"""What `take`, `where` and `updated` change of the one table a view shows."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.compute as pc

if TYPE_CHECKING:
	from collections.abc import Callable, Collection

	from rexlib_metadata.schema import Schema, TableSchema

	Rows = Collection[int] | Collection[bool] | pa.Array | pa.ChunkedArray


class Edit:
	"""The rows kept and the updates of one table, read a chunk at a time."""

	def __init__(
		self,
		name: str,
		updates: pa.Table | None,
		kept: Mask | Positions | None,
	) -> None:
		"""Edit table `name`: keep `kept` of its rows, then apply `updates`."""
		self.name = name
		self.updates = updates
		self.kept = kept
		self._read = 0
		self._written = 0

	def rows_of(self, table: pa.Table) -> pa.Table:
		"""Return the rows of the next chunk that the selection keeps."""
		if self.kept is None:
			return table
		count = table.num_rows
		picked = self.kept.picked(self._read, count)
		self._read += count
		return table.take(picked)

	def updates_of(self, rows: int) -> pa.Table | None:
		"""Return the updates of the next `rows` rows."""
		if self.updates is None:
			return None
		piece = self.updates.slice(self._written, rows)
		self._written += rows
		if piece.num_rows < rows:
			raise _updates_mismatch(
				self.updates, f"at least {self._written}", self.name
			)
		return piece

	def check(self) -> None:
		"""Raise if the selection or the updates did not fit the rows read."""
		if self.kept is not None:
			self.kept.check(self._read)
		if self.updates is not None and self.updates.num_rows != self._written:
			raise _updates_mismatch(self.updates, str(self._written), self.name)


class Mask:
	"""A boolean per row, read a chunk at a time."""

	def __init__(self, mask: pa.Array, table: str) -> None:
		"""Keep the rows of `table` where `mask` is true."""
		self._kept = mask
		self._table = table

	def picked(self, start: int, count: int) -> pa.Array:
		"""Return the positions kept among `count` rows from `start`."""
		return pc.indices_nonzero(
			self._kept.slice(start, count).fill_null(False)
		)

	def check(self, rows: int) -> None:
		"""Raise if the mask does not hold one boolean per row read."""
		if len(self._kept) != rows:
			raise _mask_mismatch(len(self._kept), rows, self._table)


class Positions:
	"""Increasing row positions, read a chunk at a time."""

	def __init__(self, positions: pa.Array, table: str) -> None:
		"""Keep the rows of `table` at `positions`."""
		self._kept = positions
		self._table = table
		self._taken = 0

	def picked(self, start: int, count: int) -> pa.Array:
		"""Return the positions kept among `count` rows from `start`."""
		window = self._kept.slice(self._taken, count)
		inside = len(
			pc.indices_nonzero(pc.less(window, pa.scalar(start + count)))
		)
		self._taken += inside
		return pc.subtract(window.slice(0, inside), start)

	def check(self, rows: int) -> None:
		"""Raise if a position lies past the rows read."""
		if self._taken < len(self._kept):
			raise outside(self._table, rows)


def streamed(rows: pa.Array, table: str) -> Mask | Positions | None:
	"""Return the selection read a chunk at a time, or None if it cannot be.

	Positions out of order cannot.
	"""
	if pa.types.is_boolean(rows.type):
		return Mask(rows, table)
	if _increasing(rows):
		return Positions(rows.cast(pa.int64()), table)
	return None


def _increasing(selection: pa.Array) -> bool:
	if not pa.types.is_integer(selection.type) or selection.null_count:
		return False
	if not len(selection):
		return True
	positions = selection.cast(pa.int64())
	steps = pc.subtract(
		positions.slice(1), positions.slice(0, len(positions) - 1)
	)
	return (
		positions[0].as_py() >= 0
		and pc.all(pc.greater(steps, pa.scalar(0))).as_py()
	)


def positions(rows: pa.Array, count: int, table: str) -> pa.Array:
	"""Return the positions `rows` keeps of a table of `count` rows."""
	if pa.types.is_boolean(rows.type):
		if len(rows) != count:
			raise _mask_mismatch(len(rows), count, table)
		return pc.indices_nonzero(rows.fill_null(False))
	beyond = pc.or_(
		pc.less(rows, pa.scalar(0)),
		pc.greater_equal(rows, pa.scalar(count)),
	)
	if rows.null_count or pc.any(beyond).as_py():
		raise outside(table, count)
	return rows.cast(pa.int64())


def as_positions(rows: Rows) -> pa.Array:
	"""Return `rows` as an Arrow array of row positions."""
	return _selection(rows, pa.int64(), pa.types.is_integer, "row positions")


def as_mask(rows: Rows) -> pa.Array:
	"""Return `rows` as an Arrow array of one boolean per row."""
	wanted = "a boolean per row"
	return _selection(rows, pa.bool_(), pa.types.is_boolean, wanted)


def _selection(
	rows: Rows,
	empty: pa.DataType,
	accepted: Callable[[pa.DataType], bool],
	wanted: str,
) -> pa.Array:
	array = _as_array(rows)
	if pa.types.is_null(array.type) and not len(array):
		return array.cast(empty)
	if not accepted(array.type):
		raise TypeError(f"Rows hold {array.type}, where {wanted} belong")
	return array


def _as_array(rows: Rows) -> pa.Array:
	to_arrow = getattr(rows, "to_arrow", None)
	found = rows if to_arrow is None else to_arrow()
	if isinstance(found, pa.ChunkedArray):
		return found.combine_chunks()
	return found if isinstance(found, pa.Array) else pa.array(found)


def shown(schema: Schema, name: str, joined: bool) -> list[TableSchema]:
	"""Return table `name` and, when joined, the tables it points at."""
	tables = [schema[name]]
	if joined:
		tables += [schema[r.related] for r in schema.relations_of(name)]
	return tables


def own_updates(
	frame: pa.Table, current: pa.Table, schema: Schema, name: str
) -> pa.Table:
	"""Return the columns of `frame` table `name` holds.

	A column of a table it points at, joined into `current`, raises if
	`frame` changes it.
	"""
	own = [c for c in frame.column_names if c in schema[name]]
	changed = [
		column
		for column in frame.column_names
		if column not in own
		and not frame.column(column)
		.cast(current.column(column).type)
		.equals(current.column(column))
	]
	if changed:
		raise ValueError(
			f"updates changes {', '.join(repr(c) for c in changed)}, which "
			f"table '{name}' does not hold but points at; update them "
			"through the table that holds them, as result[name].updated(...)"
		)
	return frame.select(own)


def merged(canonical: pa.Table, updates: pa.Table | None) -> pa.Table:
	"""Return `canonical` with the columns of `updates` in place of its own."""
	if updates is None:
		return canonical
	for name in updates.column_names:
		column = updates.column(name)
		if name in canonical.column_names:
			index = canonical.column_names.index(name)
			canonical = canonical.set_column(index, name, column)
		else:
			canonical = canonical.append_column(name, column)
	return canonical


def _updates_mismatch(updates: pa.Table, written: str, name: str) -> ValueError:
	return ValueError(
		f"updates holds {updates.num_rows} rows where {written} of table "
		f"'{name}' are read; it holds one per row, in the same order: one "
		"per row of the table, or one per row kept"
	)


def _mask_mismatch(length: int, count: int, table: str) -> ValueError:
	return ValueError(
		f"The mask holds {length} booleans where table '{table}' holds "
		f"{count} rows"
	)


def outside(table: str, count: int) -> ValueError:
	"""Return the error of a position outside a table of `count` rows."""
	return ValueError(
		f"A position lies outside table '{table}', which holds {count} rows"
	)
