# SPDX-License-Identifier: LGPL-2.1-or-later

import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

import rexlib_metadata as rxm
from rexlib_metadata.convention import RawTable
from rexlib_metadata.conventions.relion import relion4_bundle
from rexlib_metadata.conventions.sqlite import SqliteReader, SqliteWriter

STAR = Path(__file__).parent.parent / "files" / "star"


def database(tmp_path, *statements, name="data.sqlite"):
    path = tmp_path / name
    with closing(sqlite3.connect(path)) as connection, connection:
        for statement in statements:
            connection.execute(statement)
    return str(path)


def particles(tmp_path, rows=3, name="data.sqlite"):
    values = ", ".join(f"({i}, {i * 1.5}, 'img_{i}.mrc')" for i in range(rows))
    return database(
        tmp_path,
        "CREATE TABLE particles (id INTEGER, defocus REAL, path TEXT)",
        f"INSERT INTO particles VALUES {values}",
        "CREATE TABLE \"properties\" (key VARCHAR(20), value)",
        "INSERT INTO properties VALUES ('sampling', 1.2)",
        name=name,
    )


def test_every_table_reads_in_the_order_it_was_made(tmp_path):
    raw = rxm.read(particles(tmp_path)).raw

    assert raw.names == ("particles", "properties")


def test_a_column_has_the_type_the_file_declares(tmp_path):
    table = rxm.read(particles(tmp_path)).raw["particles"].tables()[0].table

    assert table.schema == pa.schema(
        [("id", pa.int64()), ("defocus", pa.float64()), ("path", pa.string())]
    )
    assert table.column("defocus").to_pylist() == [0.0, 1.5, 3.0]


def test_a_column_declaring_nothing_is_text(tmp_path):
    raw = rxm.read(particles(tmp_path)).raw["properties"].to_pandas()

    assert raw["key"].tolist() == ["sampling"]
    assert raw["value"].tolist() == ["1.2"]


def test_a_value_its_declared_type_cannot_hold_says_where(tmp_path):
    path = database(
        tmp_path,
        "CREATE TABLE t (n INTEGER)",
        "INSERT INTO t VALUES ('not a number')",
    )
    reader = SqliteReader()

    with pytest.raises(ValueError, match="'n' of table 't'"):
        reader.read_tables(path)


def test_a_read_keeping_columns_selects_only_those(tmp_path):
    tables = SqliteReader().read_tables_keeping(
        particles(tmp_path), {"path", "value"}
    )

    assert [t.schema.column_names for t in tables] == [("path",), ("value",)]


def test_chunks_come_from_one_cursor_per_table(tmp_path):
    chunks = list(SqliteReader().read_chunks(particles(tmp_path, rows=5), 2))

    assert [(at, t.table.num_rows) for at, t in chunks] == [
        (0, 2),
        (0, 2),
        (0, 1),
        (1, 1),
    ]


def test_a_table_of_no_rows_is_one_empty_chunk(tmp_path):
    path = database(tmp_path, "CREATE TABLE t (n INTEGER)")

    chunks = list(SqliteReader().read_chunks(path, 10))

    assert [(at, t.table.num_rows) for at, t in chunks] == [(0, 0)]


def test_a_missing_file_raises_file_not_found(tmp_path):
    reader = SqliteReader()
    path = str(tmp_path / "nothing.sqlite")

    with pytest.raises(FileNotFoundError):
        reader.read_tables(path)


def test_a_file_that_is_not_sqlite_says_so(tmp_path):
    path = tmp_path / "text.sqlite"
    path.write_text("data_\nloop_\n_rlnA\n1\n")
    reader = SqliteReader()

    with pytest.raises(ValueError, match="not an SQLite file"):
        reader.read_tables(str(path))


def test_what_was_read_writes_back_the_same(tmp_path):
    source = rxm.read(particles(tmp_path)).raw
    out = str(tmp_path / "out.db")

    source.write(out)
    again = rxm.read(out).raw

    assert again.names == source.names
    for name in source.names:
        pd.testing.assert_frame_equal(
            source[name].to_pandas(), again[name].to_pandas()
        )


def test_a_star_file_writes_as_sqlite_tables_of_text(tmp_path):
    out = str(tmp_path / "out.sqlite")

    rxm.read(str(STAR / "rln3.1_data_style.star")).raw.write(out)
    again = rxm.read(out).raw

    assert again.names == ("block_1", "block_2", "block_3")
    assert again["block_2"].tables()[0].table.schema.types[0] == pa.string()


def test_a_write_replaces_what_the_file_held(tmp_path):
    path = particles(tmp_path)
    table = RawTable.of("only", pa.table({"n": [1, 2]}))

    SqliteWriter().write_tables(path, [table])

    assert rxm.read(path).raw.names == ("only",)


def test_a_column_sqlite_has_no_type_for_is_refused(tmp_path):
    table = RawTable.of("t", pa.table({"when": pa.array([0], pa.date32())}))
    writer = SqliteWriter()

    with pytest.raises(ValueError, match="'when' of table 't'"):
        writer.write_tables(str(tmp_path / "out.sqlite"), [table])


def test_no_convention_reads_a_generic_database(tmp_path):
    result = rxm.read(particles(tmp_path))

    assert result.names == ()
    assert result.raw.names == ("particles", "properties")


def test_a_table_keeping_none_of_the_columns_keeps_its_rows(tmp_path):
    reader = SqliteReader()
    path = particles(tmp_path)

    kept = reader.read_tables_keeping(path, {"path"})
    chunked = list(reader.read_chunks(path, 10, {"path"}))

    assert [t.table.num_rows for t in kept] == [3, 1]
    assert kept[1].table.num_columns == 0
    assert [t.table.num_rows for _, t in chunked] == [3, 1]


def test_a_canonical_read_of_some_columns_reads_a_file_of_tables(tmp_path):
    star = Path(__file__).parent.parent / "files" / "star"
    path = str(tmp_path / "subtomo.sqlite")
    rxm.read(str(star / "relion3.1_subtomo.star")).raw.write(path)

    result = rxm.read(path, columns=["angle_rot"], bundle=relion4_bundle())

    assert len(result["particles"].to_pandas()) == 57


def test_two_tables_of_one_name_are_refused(tmp_path):
    tables = [
        RawTable.of("t", pa.table({"a": [1]})),
        RawTable.of("t", pa.table({"a": [2]})),
    ]
    writer = SqliteWriter()

    with pytest.raises(ValueError, match="share a name"):
        writer.write_tables(str(tmp_path / "out.sqlite"), tables)
