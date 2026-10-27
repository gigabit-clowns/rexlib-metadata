# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import pytest

import rexlib_metadata as rxm

FILES = Path(__file__).parent.parent / "files" / "star"

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
    pytest.param("loop_single_quote.star", {"": (2, 8)}, id="single_quotes"),
    pytest.param("empty_loop.star", {"": (0, 1)}, id="no_rows"),
]


@pytest.mark.parametrize(("name", "tables"), WHOLE_FILES)
def test_every_table_of_a_real_file(name, tables):
    result = rxm.read(str(FILES / name)).raw

    assert result.names == tuple(tables)
    for table, shape in tables.items():
        assert result[table].to_pandas().shape == shape


def test_a_file_of_one_table_needs_no_name():
    df = rxm.read(str(FILES / "one_loop.star")).raw.to_pandas()
    assert df.shape == (16, 12)


def test_a_file_of_several_tables_asks_which_one():
    result = rxm.read(str(FILES / "postprocess.star")).raw

    with pytest.raises(ValueError, match="'general', 'fsc', 'guinier'"):
        result.to_pandas()


def test_a_table_nobody_has_raises_with_the_ones_there_are():
    result = rxm.read(str(FILES / "postprocess.star")).raw

    with pytest.raises(KeyError, match="no table 'particles'"):
        result["particles"]


def test_relion_writes_the_column_index_as_a_comment():
    result = rxm.read(str(FILES / "rln3.1_data_style.star")).raw

    assert list(result["block_2"].to_pandas().columns) == [
        "_rlnImageName",
        "_rlnMicrographName",
        "_rlnCoordinateX",
        "_rlnCoordinateY",
        "_rlnCoordinateZ",
    ]


def test_the_optics_of_a_relion_file_is_its_own_table():
    optics = rxm.read(str(FILES / "rln3.1_data_style.star")).raw["block_1"]
    df = optics.to_pandas()

    assert df["_rlnVoltage"][0] == "300.000000"
    assert df["_rlnImagePixelSize"][0] == "1.04000"


def test_quoting_survives_every_shape_of_it():
    df = rxm.read(str(FILES / "loop_single_quote.star")).raw.to_pandas()

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
    df = rxm.read(str(FILES / "run_it025_optimiser_3D.star")).raw.to_pandas()

    assert df["_rlnOutputRootName"][0] == "Class3D/job020/run"
    assert df["_rlnChangesOptimalClasses"][0] == "0.493386"
