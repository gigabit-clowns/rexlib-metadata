# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

import rexlib_metadata as rxm
from rexlib_metadata.convention import RawTable
from rexlib_metadata.formats.star import StarReader, StarWriter

from .support import STAR

FIXTURES = Path(__file__).parent / "fixtures"


def test_file_not_found_raises_on_materialize():
    result = rxm.read(str(FIXTURES / "nonexistent.star"))
    with pytest.raises(FileNotFoundError, match="nonexistent"):
        result.raw.to_pandas()


def test_a_malformed_file_raises_a_value_error_naming_the_line(tmp_path):
    broken = tmp_path / "broken.star"
    broken.write_text("data_p\n\nloop_\n_a\n_b\n1\n")

    result = rxm.read(str(broken))

    with pytest.raises(ValueError, match=r"broken\.star:6"):
        result.raw.to_pandas()


QUOTED = FIXTURES / "quoted.star"


def test_quoted_paths_keep_their_spaces():
    df = rxm.read(str(QUOTED)).raw.to_pandas()
    assert list(df["_rlnMicrographName"]) == [
        "folder with spaces/mic 001.mrcs",
        "another folder/mic 002.mrcs",
        "plain/mic_003.mrcs",
    ]


def test_trailing_comment_is_not_a_value():
    df = rxm.read(str(QUOTED)).raw.to_pandas()
    assert df.shape == (3, 3)
    assert list(df["_rlnCoordinateX"]) == ["1024.0", "2048.0", "3072.0"]


def test_a_missing_file_carries_its_path(tmp_path):
    path = str(tmp_path / "nothing.star")
    reader = StarReader()

    with pytest.raises(FileNotFoundError) as raised:
        reader.read_tables(path)

    assert raised.value.filename == path


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("rln3.1_data_style.star", id="optics-and-particles"),
        pytest.param("postprocess.star", id="tags-and-loops"),
        pytest.param("empty_loop.star", id="empty-loop"),
    ],
)
def test_schemas_are_what_a_whole_read_holds(name):
    path = str(STAR / name)
    reader = StarReader()

    schemas = reader.read_schemas(path)

    assert schemas == [table.schema for table in reader.read_tables(path)]


def _written(name, tmp_path):
    source = rxm.read(str(STAR / name)).raw
    out = tmp_path / "out.star"
    source.write(str(out))
    return source, rxm.read(str(out)).raw


def test_what_was_read_writes_back_the_same(tmp_path):
    source, again = _written("one_loop.star", tmp_path)

    pd.testing.assert_frame_equal(source.to_pandas(), again.to_pandas())


def test_every_block_of_a_file_survives(tmp_path):
    source, again = _written("rln3.1_data_style.star", tmp_path)

    assert again.names == source.names
    for name in source.names:
        pd.testing.assert_frame_equal(
            source[name].to_pandas(), again[name].to_pandas()
        )


def test_a_quoted_value_survives_the_round_trip(tmp_path):
    source, again = _written("loop_single_quote.star", tmp_path)

    pd.testing.assert_frame_equal(source.to_pandas(), again.to_pandas())


def test_a_table_of_no_rows_survives(tmp_path):
    source, again = _written("empty_loop.star", tmp_path)

    assert again.names == source.names
    assert again.to_pandas().shape == source.to_pandas().shape


def test_a_block_of_tags_comes_back_as_a_loop_of_one_row(tmp_path):
    source, again = _written("run_it025_optimiser_3D.star", tmp_path)

    pd.testing.assert_frame_equal(source.to_pandas(), again.to_pandas())


def test_one_block_can_be_written_on_its_own(tmp_path):
    source = rxm.read(str(STAR / "rln3.1_data_style.star")).raw
    out = tmp_path / "out.star"

    source["block_1"].write(str(out))

    assert rxm.read(str(out)).raw.names == ("block_1",)


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
    source = rxm.read(str(STAR / "one_loop.star")).raw

    with pytest.raises(OSError, match="no_such_directory"):
        source.write(str(tmp_path / "no_such_directory" / "out.star"))


def test_a_table_with_no_name_is_an_anonymous_block(tmp_path):
    out = tmp_path / "out.star"
    table = RawTable.of("", pa.table({"_rlnCoordinateX": ["1.0"]}))

    StarWriter().write_tables(str(out), [table])
    again = rxm.read(str(out)).raw

    assert out.read_text().splitlines()[0] == "data_"
    assert again.names == ("",)
    assert again[""].to_pandas()["_rlnCoordinateX"].tolist() == ["1.0"]


def test_a_table_held_in_several_chunks_is_written_whole(tmp_path):
    out = tmp_path / "out.star"
    first = pa.table({"_rlnA": ["1", "2"]})
    table = pa.concat_tables([first, pa.table({"_rlnA": ["3"]})])

    StarWriter().write_tables(str(out), [RawTable.of("p", table)])

    again = rxm.read(str(out)).raw.to_pandas()
    assert again["_rlnA"].tolist() == ["1", "2", "3"]


WHOLE_FILES = [
    pytest.param("one_loop.star", {"particles": (16, 12)}, id="one_loop"),
    pytest.param(
        "postprocess.star",
        {"general": (1, 6), "fsc": (49, 7), "guinier": (49, 3)},
        id="relion_postprocess",
    ),
    pytest.param(
        "rln3.1_data_style.star",
        {"block_1": (1, 7), "block_2": (2, 5), "block_3": (2, 5)},
        id="relion_3.1",
    ),
    pytest.param(
        "run_it025_optimiser_3D.star",
        {"optimiser_general": (1, 84)},
        id="relion_optimiser",
    ),
    pytest.param(
        "single_line_middle_of_multiblock.star",
        {"block_1": (1, 5), "block_2": (1, 5)},
        id="one_row_blocks",
    ),
    pytest.param(
        "two_basic_blocks.star",
        {"block_0": (1, 3), "block_1": (1, 3)},
        id="starfile_tags",
    ),
    pytest.param(
        "relion3.1_subtomo.star",
        {"optics": (1, 7), "particles": (57, 22)},
        id="relion_3.1_subtomograms",
    ),
    pytest.param("loop_single_quote.star", {"": (2, 8)}, id="single_quotes"),
    pytest.param("empty_loop.star", {"": (0, 1)}, id="no_rows"),
]


@pytest.mark.parametrize(("name", "tables"), WHOLE_FILES)
def test_every_table_of_a_real_file(name, tables):
    result = rxm.read(str(STAR / name)).raw

    assert result.names == tuple(tables)
    for table, shape in tables.items():
        assert result[table].to_pandas().shape == shape


def test_a_file_of_one_table_needs_no_name():
    df = rxm.read(str(STAR / "one_loop.star")).raw.to_pandas()
    assert df.shape == (16, 12)


def test_a_file_of_several_tables_asks_which_one():
    result = rxm.read(str(STAR / "postprocess.star")).raw

    with pytest.raises(ValueError, match="'general', 'fsc', 'guinier'"):
        result.to_pandas()


def test_a_table_nobody_has_raises_with_the_ones_there_are():
    result = rxm.read(str(STAR / "postprocess.star")).raw

    with pytest.raises(KeyError, match="no table 'particles'"):
        result["particles"]


def test_relion_writes_the_column_index_as_a_comment():
    result = rxm.read(str(STAR / "rln3.1_data_style.star")).raw

    assert list(result["block_2"].to_pandas().columns) == [
        "_rlnImageName",
        "_rlnMicrographName",
        "_rlnCoordinateX",
        "_rlnCoordinateY",
        "_rlnCoordinateZ",
    ]


def test_the_optics_of_a_relion_file_is_its_own_table():
    optics = rxm.read(str(STAR / "rln3.1_data_style.star")).raw["block_1"]
    df = optics.to_pandas()

    assert df["_rlnVoltage"][0] == "300.000000"
    assert df["_rlnImagePixelSize"][0] == "1.04000"


def test_quoting_survives_every_shape_of_it():
    df = rxm.read(str(STAR / "loop_single_quote.star")).raw.to_pandas()

    assert df.to_numpy().tolist()[0] == [
        "noquote",
        "quote string",
        " ",
        "",
        "4.0",
        "5.0",
        "6.0",
        "",
    ]


def test_an_optimiser_file_keeps_its_names_and_values_together():
    df = rxm.read(str(STAR / "run_it025_optimiser_3D.star")).raw.to_pandas()

    assert df["_rlnOutputRootName"][0] == "Class3D/job020/run"
    assert df["_rlnChangesOptimalClasses"][0] == "0.493386"
