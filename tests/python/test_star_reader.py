from pathlib import Path

import pytest

import rexlib_metadata as rm

FIXTURES = Path(__file__).parent / "fixtures"
MINI = FIXTURES / "mini.star"

EXPECTED_COLUMNS = ["_rlnAngleRot", "_rlnAngleTilt", "_rlnCoordinateX", "_rlnCoordinateY"]
EXPECTED_ROWS = 3


def test_read_returns_read_result():
    assert isinstance(rm.read(str(MINI)), rm.ReadResult)


def test_unknown_extension_raises():
    with pytest.raises(ValueError, match="No reader registered"):
        rm.read("data.csv")


def test_file_not_found_raises_on_materialize():
    result = rm.read(str(FIXTURES / "nonexistent.star"))
    with pytest.raises(RuntimeError, match="nonexistent"):
        result.to_pandas()


def test_to_pandas_shape():
    df = rm.read(str(MINI)).to_pandas()
    assert df.shape == (EXPECTED_ROWS, len(EXPECTED_COLUMNS))


def test_to_pandas_column_names():
    df = rm.read(str(MINI)).to_pandas()
    assert list(df.columns) == EXPECTED_COLUMNS


def test_to_pandas_values():
    df = rm.read(str(MINI)).to_pandas()
    assert list(df["_rlnAngleRot"]) == ["10.5", "30.2", "50.7"]
    assert list(df["_rlnCoordinateX"]) == ["1024.0", "2048.0", "3072.0"]


def test_to_pandas_all_strings():
    df = rm.read(str(MINI)).to_pandas()
    for col in df.columns:
        assert all(isinstance(v, str) for v in df[col])


def test_to_polars_shape():
    pl = pytest.importorskip("polars")
    df = rm.read(str(MINI)).to_polars()
    assert df.shape == (EXPECTED_ROWS, len(EXPECTED_COLUMNS))


def test_to_polars_column_names():
    pytest.importorskip("polars")
    df = rm.read(str(MINI)).to_polars()
    assert df.columns == EXPECTED_COLUMNS


def test_to_polars_values():
    pytest.importorskip("polars")
    df = rm.read(str(MINI)).to_polars()
    assert df["_rlnAngleRot"].to_list() == ["10.5", "30.2", "50.7"]
    assert df["_rlnCoordinateX"].to_list() == ["1024.0", "2048.0", "3072.0"]


def test_to_polars_all_strings():
    pl = pytest.importorskip("polars")
    df = rm.read(str(MINI)).to_polars()
    for col in df.columns:
        assert df[col].dtype == pl.String
