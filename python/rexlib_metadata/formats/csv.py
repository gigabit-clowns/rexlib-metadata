# SPDX-License-Identifier: LGPL-2.1-or-later

"""Reading the `.csv` cryoSPARC v0.65 and earlier exported.

A file is one table, named on its `_table` line, then `_header` over a line
of column names and `_dtypes` over a line of their types, `int`, `float` or
`string`; each column is read as its type says. Blank lines around the
table are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.csv as pa_csv

from rexlib_metadata.abc import Reader
from rexlib_metadata.convention import RawSchema, RawTable

if TYPE_CHECKING:
	from collections.abc import Iterable, Iterator, Set

_TYPES: dict[str, pa.DataType] = {
	"int": pa.int64(),
	"float": pa.float64(),
	"string": pa.string(),
}


class CsvReader(Reader):
	"""Reads a cryoSPARC `.csv` file through Arrow's CSV reader."""

	def read_tables(self, path: str) -> list[RawTable]:
		"""Read every row of the file at `path`."""
		return [_read(path, None)]

	def read_schemas(self, path: str) -> list[RawSchema]:
		"""Name the file's table and columns, reading no row."""
		header = _header(path)
		return [RawSchema(header.name, header.names)]

	def read_tables_keeping(
		self, path: str, columns: Set[str]
	) -> list[RawTable]:
		"""Read only the columns `columns` names."""
		return [_read(path, columns)]

	def read_chunks(
		self, path: str, size: int, columns: Set[str] | None = None
	) -> Iterator[tuple[int, RawTable]]:
		"""Read `size` rows at a time, as Arrow's reader streams them."""
		header = _header(path)
		kept = header.kept(columns)
		try:
			reader = pa_csv.open_csv(
				path,
				read_options=header.read_options(),
				convert_options=header.convert_options(kept),
			)
			for table in _sized(reader, size):
				yield 0, RawTable.of(header.name, table.select(list(kept)))
		except pa.ArrowInvalid as error:
			raise ValueError(f"{path}: {error}") from None


@dataclass(frozen=True)
class _Header:
	"""What the lines before a file's rows say."""

	name: str
	names: tuple[str, ...]
	types: tuple[pa.DataType, ...]
	lines: int

	def kept(self, columns: Set[str] | None) -> tuple[str, ...]:
		return tuple(n for n in self.names if columns is None or n in columns)

	def read_options(self) -> pa_csv.ReadOptions:
		names = list(self.names)
		return pa_csv.ReadOptions(skip_rows=self.lines, column_names=names)

	def convert_options(self, kept: tuple[str, ...]) -> pa_csv.ConvertOptions:
		return pa_csv.ConvertOptions(
			column_types=dict(zip(self.names, self.types, strict=True)),
			include_columns=list(kept or self.names[:1]),
			null_values=[""],
			strings_can_be_null=False,
		)


def _read(path: str, columns: Set[str] | None) -> RawTable:
	header = _header(path)
	kept = header.kept(columns)
	try:
		table = pa_csv.read_csv(
			path,
			read_options=header.read_options(),
			convert_options=header.convert_options(kept),
		)
	except pa.ArrowInvalid as error:
		raise ValueError(f"{path}: {error}") from None
	return RawTable.of(header.name, table.select(list(kept)))


def _header(path: str) -> _Header:
	if not Path(path).is_file():
		raise FileNotFoundError(f"No such file: {path!r}")
	with Path(path).open(encoding="utf-8") as file:
		lines = _Lines(path, file)
		name = lines.after("_table,")
		lines.keyword("_header")
		names = tuple(lines.after("").split(","))
		lines.keyword("_dtypes")
		types = tuple(lines.after("").split(","))
		read = lines.before_next()
	if len(types) != len(names):
		raise ValueError(
			f"{path} declares {len(types)} types for {len(names)} columns"
		)
	return _Header(name, names, _typed(path, names, types), read)


class _Lines:
	"""The lines of a file that are not blank, with their numbers."""

	def __init__(self, path: str, file: Iterable[str]) -> None:
		self._path = path
		self._remaining = (
			(number, line.rstrip("\r\n"))
			for number, line in enumerate(file, start=1)
			if line.strip()
		)
		self._number = 0

	def after(self, start: str) -> str:
		"""Return what the next line holds after `start`, which it opens."""
		line = self._next(start or "a line of names")
		if not line.startswith(start):
			raise self._refused(line, start)
		return line[len(start) :]

	def keyword(self, word: str) -> None:
		"""Read the next line, which is `word` and nothing else."""
		line = self._next(word)
		if line != word:
			raise self._refused(line, word)

	def before_next(self) -> int:
		"""Return how many lines come before the next that is not blank."""
		found = next(self._remaining, None)
		return self._number if found is None else found[0] - 1

	def _next(self, expected: str) -> str:
		found = next(self._remaining, None)
		if found is None:
			raise ValueError(
				f"{self._path} is not a cryoSPARC CSV: it ends where "
				f"{expected!r} belongs"
			)
		self._number, line = found
		return line

	def _refused(self, line: str, expected: str) -> ValueError:
		return ValueError(
			f"{self._path} is not a cryoSPARC CSV: line {self._number} is "
			f"{line!r} where {expected or 'a line of names'!r} belongs"
		)


def _typed(
	path: str, names: tuple[str, ...], types: tuple[str, ...]
) -> tuple[pa.DataType, ...]:
	unknown = [
		(n, t) for n, t in zip(names, types, strict=True) if t not in _TYPES
	]
	if unknown:
		name, kind = unknown[0]
		raise ValueError(
			f"{path} declares column '{name}' as {kind!r}, where int, float "
			"or string belongs"
		)
	return tuple(_TYPES[kind] for kind in types)


def _sized(reader: pa_csv.CSVStreamingReader, size: int) -> Iterator[pa.Table]:
	"""Yield the rows `reader` streams `size` at a time, or one empty table."""
	pending = pa.Table.from_batches([], reader.schema)
	given = False
	for batch in reader:
		pending = pa.concat_tables([pending, pa.Table.from_batches([batch])])
		while pending.num_rows >= size:
			yield pending.slice(0, size)
			pending = pending.slice(size)
			given = True
	if pending.num_rows or not given:
		yield pending
