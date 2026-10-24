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

PAIR_BLOCKS = [
    pytest.param("postprocess.star", id="relion_postprocess"),
    pytest.param("run_it025_optimiser_3D.star", id="relion_optimiser"),
    pytest.param("two_basic_blocks.star", id="starfile_pairs"),
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


@pytest.mark.parametrize("name", PAIR_BLOCKS)
def test_a_block_of_pairs_is_not_read_yet(name):
    with pytest.raises(RuntimeError, match="unexpected tokens after column"):
        rm.read(str(FILES / name)).to_pandas()
