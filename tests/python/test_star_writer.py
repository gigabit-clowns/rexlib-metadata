# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

import rexlib_metadata as rxm
from rexlib_metadata.convention import RawTable
from rexlib_metadata.formats.star import StarWriter

FILES = Path(__file__).parent.parent / "files" / "star"


def written(name, tmp_path):
    source = rxm.read(str(FILES / name)).raw
    out = tmp_path / "out.star"
    source.write(str(out))
    return source, rxm.read(str(out)).raw


def test_what_was_read_writes_back_the_same(tmp_path):
    source, again = written("one_loop.star", tmp_path)

    pd.testing.assert_frame_equal(source.to_pandas(), again.to_pandas())


def test_every_block_of_a_file_survives(tmp_path):
    source, again = written("rln3.1_data_style.star", tmp_path)

    assert again.names == source.names
    for name in source.names:
        pd.testing.assert_frame_equal(
            source[name].to_pandas(), again[name].to_pandas()
        )


def test_a_quoted_value_survives_the_round_trip(tmp_path):
    source, again = written("loop_single_quote.star", tmp_path)

    pd.testing.assert_frame_equal(source.to_pandas(), again.to_pandas())


def test_a_table_of_no_rows_survives(tmp_path):
    source, again = written("empty_loop.star", tmp_path)

    assert again.names == source.names
    assert again.to_pandas().shape == source.to_pandas().shape


def test_a_block_of_tags_comes_back_as_a_loop_of_one_row(tmp_path):
    source, again = written("run_it025_optimiser_3D.star", tmp_path)

    pd.testing.assert_frame_equal(source.to_pandas(), again.to_pandas())


def test_one_block_can_be_written_on_its_own(tmp_path):
    source = rxm.read(str(FILES / "rln3.1_data_style.star")).raw
    out = tmp_path / "out.star"

    source["block_1"].write(str(out))

    assert rxm.read(str(out)).raw.names == ("block_1",)


def test_an_extension_with_no_writer_raises(tmp_path):
    source = rxm.read(str(FILES / "one_loop.star")).raw

    with pytest.raises(ValueError, match="No writer registered"):
        source.write(str(tmp_path / "out.csv"))


def test_a_column_a_reader_would_not_see_is_refused(tmp_path):
    table = RawTable.of("particles", pa.table({"coord_x": ["1.0"]}))
    writer = StarWriter()

    with pytest.raises(ValueError, match="coord_x"):
        writer.write_tables(str(tmp_path / "out.star"), [table])


def test_a_column_that_is_not_text_is_refused(tmp_path):
    numbers = pa.table({"_rlnClassNumber": pa.array([1], type=pa.int32())})
    table = RawTable.of("p", numbers)
    writer = StarWriter()

    with pytest.raises(ValueError, match="Utf8"):
        writer.write_tables(str(tmp_path / "out.star"), [table])


def test_a_destination_that_cannot_be_opened_raises(tmp_path):
    source = rxm.read(str(FILES / "one_loop.star")).raw

    with pytest.raises(OSError, match="no_such_directory"):
        source.write(str(tmp_path / "no_such_directory" / "out.star"))


def test_a_table_with_no_name_is_an_anonymous_block(tmp_path):
    out = tmp_path / "out.star"
    table = RawTable.of("", pa.table({"_rlnCoordinateX": ["1.0"]}))

    StarWriter().write_tables(str(out), [table])
    again = rxm.read(str(out)).raw

    assert out.read_text().splitlines()[0] == "data_"
    assert again.names == ("",)
    assert len(again[""].to_pandas()) == 1


def test_a_table_held_in_several_chunks_is_written_whole(tmp_path):
    out = tmp_path / "out.star"
    first = pa.table({"_rlnA": ["1", "2"]})
    table = pa.concat_tables([first, pa.table({"_rlnA": ["3"]})])

    StarWriter().write_tables(str(out), [RawTable.of("p", table)])

    again = rxm.read(str(out)).raw.to_pandas()
    assert again["_rlnA"].tolist() == ["1", "2", "3"]
