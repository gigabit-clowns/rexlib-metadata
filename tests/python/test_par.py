# SPDX-License-Identifier: LGPL-2.1-or-later

import pyarrow as pa
import pytest

from rexlib_metadata.formats.par import ParReader

from .support import PAR, STAR

_LINES = PAR.read_text().splitlines()


def _written(tmp_path, lines):
	path = tmp_path / "made.par"
	path.write_text("\n".join(lines) + "\n")
	return str(path)


def test_a_par_file_is_one_table_named_by_its_first_line():
	(table,) = ParReader().read_tables(str(PAR))

	assert table.schema.table_name == ""
	assert table.table.column_names == _LINES[0].split()
	assert table.table.num_rows == len(_LINES) - 1
	assert set(table.table.schema.types) == {pa.string()}


def test_each_value_is_the_text_the_file_holds_in_its_column():
	(table,) = ParReader().read_tables(str(PAR))

	assert table.table.to_pylist()[0] == dict(
		zip(_LINES[0].split(), _LINES[1].split(), strict=True)
	)


def test_values_that_run_into_each_other_split_by_position(tmp_path):
	header = "C           PSI   THETA"
	row = "      1 -123.45-1110.00"
	path = _written(tmp_path, [header, row])

	(table,) = ParReader().read_tables(path)

	assert table.table.to_pylist() == [
		{"C": "1", "PSI": "-123.45", "THETA": "-1110.00"}
	]


def test_a_comment_line_is_not_a_row(tmp_path):
	path = _written(tmp_path, [*_LINES, "C  Average score: 50.00", ""])

	(table,) = ParReader().read_tables(path)

	assert table.table.num_rows == len(_LINES) - 1


def test_the_schema_is_what_a_whole_read_holds():
	reader = ParReader()

	(schema,) = reader.read_schemas(str(PAR))
	(table,) = reader.read_tables(str(PAR))

	assert schema == table.schema


def test_a_read_keeping_columns_reads_only_those():
	(table,) = ParReader().read_tables_keeping(str(PAR), {"PSI", "C"})

	assert table.table.column_names == ["C", "PSI"]


def test_a_read_keeping_none_of_the_columns_keeps_its_rows():
	reader = ParReader()

	(table,) = reader.read_tables_keeping(str(PAR), {"nope"})
	chunks = list(reader.read_chunks(str(PAR), 4, {"nope"}))

	assert table.table.num_columns == 0
	assert table.table.num_rows == len(_LINES) - 1
	assert [chunk.table.num_rows for _, chunk in chunks] == [4, 4, 2]


def test_chunks_put_back_together_are_the_whole_read():
	reader = ParReader()
	(table,) = reader.read_tables(str(PAR))

	chunks = list(reader.read_chunks(str(PAR), 3))

	assert [ordinal for ordinal, _ in chunks] == [0] * 4
	assert pa.concat_tables([c.table for _, c in chunks]).equals(table.table)


def test_a_file_of_no_rows_is_one_empty_chunk(tmp_path):
	path = _written(tmp_path, _LINES[:1])

	chunks = list(ParReader().read_chunks(path, 4))

	assert [chunk.table.num_rows for _, chunk in chunks] == [0]
	assert chunks[0][1].table.column_names == _LINES[0].split()


@pytest.mark.parametrize(
	("lines", "message"),
	[
		pytest.param(
			STAR.joinpath("one_loop.star").read_text().splitlines(),
			"not a FREALIGN .par",
			id="a-star-file",
		),
		pytest.param(
			[_LINES[0], _LINES[1][:60]], r"made\.par:2: a row of 16", id="short"
		),
		pytest.param(
			[_LINES[0], _LINES[1] + "   7.00"],
			r"made\.par:2: a row of 16",
			id="long",
		),
	],
)
def test_a_file_that_is_not_a_par_says_why(tmp_path, lines, message):
	path = _written(tmp_path, lines)
	reader = ParReader()

	with pytest.raises(ValueError, match=message):
		reader.read_tables(path)


def test_a_missing_par_file_raises_file_not_found(tmp_path):
	reader = ParReader()

	with pytest.raises(FileNotFoundError, match="No such file"):
		reader.read_tables(str(tmp_path / "missing.par"))
