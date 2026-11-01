# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import polars as pl
import pytest

import rexlib_metadata as rxm
from rexlib_metadata.conventions.star import StarReader

FIXTURES = Path(__file__).parent / "fixtures"
MINI = FIXTURES / "mini.star"
FILES = Path(__file__).parent.parent / "files" / "star"

EXPECTED_COLUMNS = [
    "_rlnAngleRot",
    "_rlnAngleTilt",
    "_rlnCoordinateX",
    "_rlnCoordinateY",
]
EXPECTED_ROWS = 3


def test_read_returns_read_result():
    assert isinstance(rxm.read(str(MINI)), rxm.ReadResult)


def test_unknown_extension_raises():
    with pytest.raises(ValueError, match="No reader registered"):
        rxm.read("data.csv")


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


def test_to_pandas_shape():
    df = rxm.read(str(MINI)).raw.to_pandas()
    assert df.shape == (EXPECTED_ROWS, len(EXPECTED_COLUMNS))


def test_to_pandas_column_names():
    df = rxm.read(str(MINI)).raw.to_pandas()
    assert list(df.columns) == EXPECTED_COLUMNS


def test_to_pandas_values():
    df = rxm.read(str(MINI)).raw.to_pandas()
    assert list(df["_rlnAngleRot"]) == ["10.5", "30.2", "50.7"]
    assert list(df["_rlnCoordinateX"]) == ["1024.0", "2048.0", "3072.0"]


def test_to_pandas_all_strings():
    df = rxm.read(str(MINI)).raw.to_pandas()
    for col in df.columns:
        assert all(isinstance(v, str) for v in df[col])


def test_to_polars_shape():
    df = rxm.read(str(MINI)).raw.to_polars()
    assert df.shape == (EXPECTED_ROWS, len(EXPECTED_COLUMNS))


def test_to_polars_column_names():
    df = rxm.read(str(MINI)).raw.to_polars()
    assert df.columns == EXPECTED_COLUMNS


def test_to_polars_values():
    df = rxm.read(str(MINI)).raw.to_polars()
    assert df["_rlnAngleRot"].to_list() == ["10.5", "30.2", "50.7"]
    assert df["_rlnCoordinateX"].to_list() == ["1024.0", "2048.0", "3072.0"]


def test_to_polars_all_strings():
    df = rxm.read(str(MINI)).raw.to_polars()
    for col in df.columns:
        assert df[col].dtype == pl.String


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
    path = str(FILES / name)
    reader = StarReader()

    schemas = reader.read_schemas(path)

    assert schemas == [table.schema for table in reader.read_tables(path)]
