# SPDX-License-Identifier: LGPL-2.1-or-later

"""Reading FREALIGN's `.par`, one particle a line.

The first line names the columns, each name ending where its column ends;
the first column, `C`, is the particle's number. Every other line that
starts with `C` is a comment. A file is one table, `""`, every value text.
"""

from __future__ import annotations

import re
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa

from rexlib_metadata.abc import Reader
from rexlib_metadata.convention import RawSchema, RawTable

if TYPE_CHECKING:
	from collections.abc import Iterator, Set

_WORD = re.compile(r"\S+")
_SPLIT = 2


class ParReader(Reader):
	"""Reads a FREALIGN `.par` file, splitting each row by position."""

	def read_tables(self, path: str) -> list[RawTable]:
		"""Read every row of the file at `path`."""
		return [_table(path, None)]

	def read_schemas(self, path: str) -> list[RawSchema]:
		"""Name the file's columns, reading no row."""
		names, _ = _header(path)
		return [RawSchema("", names)]

	def read_tables_keeping(
		self, path: str, columns: Set[str]
	) -> list[RawTable]:
		"""Read only the columns `columns` names."""
		return [_table(path, columns)]

	def read_chunks(
		self, path: str, size: int, columns: Set[str] | None = None
	) -> Iterator[tuple[int, RawTable]]:
		"""Read `size` rows at a time."""
		names, ends = _header(path)
		kept = [n for n in names if columns is None or n in columns]
		given = False
		pending: list[list[str]] = []
		for row in _rows(path, ends):
			pending.append(row)
			if len(pending) == size:
				yield 0, _raw(names, kept, pending)
				pending, given = [], True
		if pending or not given:
			yield 0, _raw(names, kept, pending)


def _table(path: str, columns: Set[str] | None) -> RawTable:
	names, ends = _header(path)
	kept = [n for n in names if columns is None or n in columns]
	return _raw(names, kept, list(_rows(path, ends)))


def _header(path: str) -> tuple[tuple[str, ...], tuple[int, ...]]:
	"""Return the column names and where each column ends."""
	if not Path(path).is_file():
		raise FileNotFoundError(f"No such file: {path!r}")
	with Path(path).open(encoding="utf-8") as file:
		line = file.readline().rstrip("\r\n")
	words = list(_WORD.finditer(line))
	if len(words) < _SPLIT or words[0].group() != "C":
		raise ValueError(
			f"{path} is not a FREALIGN .par: its first line is {line!r}, "
			"where C and the names of the columns belong"
		)
	return tuple(w.group() for w in words), tuple(w.end() for w in words)


def _rows(path: str, ends: tuple[int, ...]) -> Iterator[list[str]]:
	with Path(path).open(encoding="utf-8") as file:
		next(file)
		for number, line in enumerate(file, start=2):
			text = line.rstrip("\r\n")
			if text.strip() and not text.startswith("C"):
				yield _fields(path, number, text, ends)


def _fields(
	path: str, number: int, line: str, ends: tuple[int, ...]
) -> list[str]:
	"""Split `line` at the columns' ends; the first `_SPLIT` by whitespace."""
	first = line[: ends[1]].split()
	rest = [line[start:end].strip() for start, end in pairwise(ends[1:])]
	fields = [*first, *rest]
	if len(first) != _SPLIT or not all(rest) or len(line.rstrip()) > ends[-1]:
		raise ValueError(
			f"{path}:{number}: a row of {len(ends)} columns ending at "
			f"{', '.join(str(e) for e in ends)}, where it holds {line!r}"
		)
	return fields


def _raw(
	names: tuple[str, ...], kept: list[str], rows: list[list[str]]
) -> RawTable:
	columns = list(zip(*rows, strict=True)) if rows else [()] * len(names)
	by_name = dict(zip(names, columns, strict=True))
	arrays = [pa.array(by_name[name], pa.string()) for name in kept]
	table = pa.table(arrays, names=kept) if kept else _counted(len(rows))
	return RawTable.of("", table)


def _counted(rows: int) -> pa.Table:
	return pa.table({"_": pa.nulls(rows)}).drop_columns(["_"])
