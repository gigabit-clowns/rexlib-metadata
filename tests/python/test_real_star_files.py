from pathlib import Path

import pytest

import rexlib_metadata as rm

FILES = Path(__file__).parent.parent / "files" / "star"

READS = [
    pytest.param("rln3.1_data_style.star", 2, 5, id="relion_3.1_multiblock"),
    pytest.param("one_loop.star", 16, 12, id="one_loop"),
    pytest.param("loop_single_quote.star", 2, 8, id="single_quotes"),
    pytest.param("single_line_middle_of_multiblock.star", 1, 5, id="one_row"),
    pytest.param("empty_loop.star", 0, 1, id="no_rows"),
]

TAG_BLOCKS = [
    pytest.param("run_it025_optimiser_3D.star", 1, 84, id="relion_optimiser"),
    pytest.param("two_basic_blocks.star", 1, 3, id="starfile_tags"),
]


@pytest.mark.parametrize(("name", "rows", "columns"), READS)
def test_a_real_file_reads(name, rows, columns):
    df = rm.read(str(FILES / name)).to_pandas()
    assert df.shape == (rows, columns)


def test_relion_writes_the_column_index_as_a_comment():
    df = rm.read(str(FILES / "rln3.1_data_style.star")).to_pandas()
    assert list(df.columns) == [
        "_rlnImageName",
        "_rlnMicrographName",
        "_rlnCoordinateX",
        "_rlnCoordinateY",
        "_rlnCoordinateZ",
    ]


def test_quoting_survives_every_shape_of_it():
    df = rm.read(str(FILES / "loop_single_quote.star")).to_pandas()

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


@pytest.mark.parametrize(("name", "rows", "columns"), TAG_BLOCKS)
def test_a_block_of_tags_is_one_row(name, rows, columns):
    df = rm.read(str(FILES / name)).to_pandas()
    assert df.shape == (rows, columns)


def test_an_optimiser_file_keeps_its_names_and_values_together():
    df = rm.read(str(FILES / "run_it025_optimiser_3D.star")).to_pandas()

    assert df["_rlnOutputRootName"][0] == "Class3D/job020/run"
    assert df["_rlnChangesOptimalClasses"][0] == "0.493386"


def test_a_file_of_tags_then_loops_reads_the_loop():
    df = rm.read(str(FILES / "postprocess.star")).to_pandas()
    assert df.shape == (49, 3)
