# SPDX-License-Identifier: LGPL-2.1-or-later

import pyarrow as pa
import pytest

from rexlib_metadata.formats.csv import CsvReader

from .support import CSV, STAR

_LINES = CSV.read_text().split("\n")
_NAMES = _LINES[4].split(",")


def _written(tmp_path, lines, name="made.csv"):
	path = tmp_path / name
	path.write_text("\n".join(lines))
	return str(path)


def test_a_csv_file_is_one_table_typed_as_declared():
	(table,) = CsvReader().read_tables(str(CSV))

	declared = dict(zip(_NAMES, _LINES[6].split(","), strict=True))
	kinds = {"int": pa.int64(), "float": pa.float64(), "string": pa.string()}
	assert table.schema.table_name == "images"
	assert table.table.column_names == _NAMES
	for field in table.table.schema:
		assert field.type == kinds[declared[field.name]]
	assert table.table.num_rows == len([line for line in _LINES[7:] if line])


def test_the_rows_hold_what_the_file_writes():
	(table,) = CsvReader().read_tables(str(CSV))

	first = _LINES[7].split(",")
	assert table.table.column("uid")[0].as_py() == int(first[0])
	assert table.table.column("split")[0].as_py() == first[1]
	assert table.table.column("ctf_params.df1")[0].as_py() == float(first[7])


def test_the_schema_is_what_a_whole_read_holds():
	reader = CsvReader()

	(schema,) = reader.read_schemas(str(CSV))
	(table,) = reader.read_tables(str(CSV))

	assert schema == table.schema


def test_a_read_keeping_columns_reads_only_those():
	(table,) = CsvReader().read_tables_keeping(str(CSV), {"uid", "split"})

	assert table.table.column_names == ["uid", "split"]


def test_a_read_keeping_none_of_the_columns_keeps_its_rows():
	reader = CsvReader()
	(table,) = reader.read_tables_keeping(str(CSV), {"nope"})

	chunks = list(reader.read_chunks(str(CSV), 4, {"nope"}))

	assert table.table.num_columns == 0
	assert table.table.num_rows == 10
	assert [chunk.table.num_rows for _, chunk in chunks] == [4, 4, 2]


def test_chunks_put_back_together_are_the_whole_read():
	reader = CsvReader()
	(table,) = reader.read_tables(str(CSV))

	chunks = list(reader.read_chunks(str(CSV), 3))

	assert [ordinal for ordinal, _ in chunks] == [0] * 4
	assert [chunk.table.num_rows for _, chunk in chunks] == [3, 3, 3, 1]
	assert pa.concat_tables([c.table for _, c in chunks]).equals(table.table)


def test_a_table_of_no_rows_is_one_empty_chunk(tmp_path):
	path = _written(tmp_path, [*_LINES[:7], "", ""])
	reader = CsvReader()

	(table,) = reader.read_tables(path)
	chunks = list(reader.read_chunks(path, 4))

	assert table.table.num_rows == 0
	assert table.table.schema.field("uid").type == pa.int64()
	assert [chunk.table.num_rows for _, chunk in chunks] == [0]


@pytest.mark.parametrize(
	("lines", "message"),
	[
		pytest.param(
			STAR.joinpath("one_loop.star").read_text().split("\n"),
			"is 'data_particles' where '_table,' belongs",
			id="a-star-file",
		),
		pytest.param(
			[*_LINES[:5], "_types", *_LINES[6:]],
			"'_types' where '_dtypes' belongs",
			id="misspelled-keyword",
		),
		pytest.param(
			_LINES[:4], "ends where 'a line of names' belongs", id="truncated"
		),
		pytest.param(
			[*_LINES[:6], "int,string", *_LINES[7:]],
			"declares 2 types for 30 columns",
			id="types-short",
		),
		pytest.param(
			[*_LINES[:6], _LINES[6].replace("int", "bool", 1), *_LINES[7:]],
			"declares column 'uid' as 'bool'",
			id="unknown-type",
		),
		pytest.param(
			[*_LINES[:7], "x" + _LINES[7], *_LINES[8:]],
			"made.csv",
			id="value-of-another-type",
		),
	],
)
def test_a_file_that_is_not_a_cryosparc_csv_says_why(tmp_path, lines, message):
	path = _written(tmp_path, lines)
	reader = CsvReader()

	with pytest.raises(ValueError, match=message):
		reader.read_tables(path)


def test_a_missing_csv_file_raises_file_not_found(tmp_path):
	reader = CsvReader()

	with pytest.raises(FileNotFoundError, match="No such file"):
		reader.read_tables(str(tmp_path / "missing.csv"))
