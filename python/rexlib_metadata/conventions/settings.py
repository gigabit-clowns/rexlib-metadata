# SPDX-License-Identifier: LGPL-2.1-or-later

"""Optics groups told apart by the microscope setting each row holds."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pyarrow as pa
import pyarrow.compute as pc

from rexlib_metadata.convention import ReadConvention
from rexlib_metadata.conventions.relion import joined_text

if TYPE_CHECKING:
	from collections.abc import Iterable

	from rexlib_metadata.convention import ArrowColumn, RawSchema


class SettingGroup(ReadConvention):
	"""Each distinct setting a group, numbered from one as first held.

	A setting is the values of `source_columns` in one row.
	"""

	target_columns = ("optics_group",)

	def spelled(self, column: ArrowColumn) -> ArrowColumn:
		"""Return a column as the text two settings are told apart by."""
		return pc.cast(column, pa.string())

	def setting(self, table: pa.Table) -> ArrowColumn:
		"""Return each row's setting as one text."""
		values = [self.spelled(table.column(c)) for c in self.source_columns]
		return joined_text(values, "\x1f", null_replacement="")

	def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
		"""Return each distinct setting numbered from one, as first held."""
		return self.in_context([table]).load(table)

	def in_context(self, chunks: Iterable[pa.Table]) -> ReadConvention:
		"""Return the groups numbered as the whole table first holds them."""
		held: pa.Array = pa.array([], pa.string())
		for chunk in chunks:
			found = cast("pa.Array", pc.unique(self.setting(chunk)))
			fresh = found.filter(pc.invert(pc.is_in(found, value_set=held)))
			held = pa.concat_arrays([held, fresh])
		return _Numbered(self, held)


class _Numbered(ReadConvention):
	"""Groups numbered by their place among the settings of a whole table."""

	def __init__(self, grouping: SettingGroup, held: pa.Array) -> None:
		self._grouping = grouping
		self._held = held
		self.source_columns = grouping.source_columns
		self.target_columns = grouping.target_columns

	def matches(self, raw: RawSchema) -> bool:
		"""Apply where the grouping it numbers applies."""
		return self._grouping.matches(raw)

	def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
		"""Return each setting's place among those held, from one."""
		place = pc.index_in(self._grouping.setting(table), value_set=self._held)
		group = pc.add(place, pa.scalar(1, pa.int32()))
		return {"optics_group": pc.cast(group, pa.int32())}
