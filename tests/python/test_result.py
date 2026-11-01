# SPDX-License-Identifier: LGPL-2.1-or-later

import shutil
from pathlib import Path

import pandas as pd
import polars as pl
import pytest

import rexlib_metadata as rxm
from rexlib_metadata.abc import Reader, Writer
from rexlib_metadata.canonical import SCHEMA
from rexlib_metadata.conventions.relion import relion4_bundle
from rexlib_metadata.engine import source_columns
from rexlib_metadata.formats.star import StarReader
from rexlib_metadata.registry import MetadataRegistry

FILES = Path(__file__).parent.parent / "files" / "star"


class _Failing(Writer):
    def write_tables(self, path, tables):
        Path(path).write_text("half a file")
        raise RuntimeError("the disk filled up")


class _Plain(Reader):
    def read_tables(self, path):
        return StarReader().read_tables(path)


class _Spy(StarReader):
    def __init__(self):
        self.kept = []

    def read_tables(self, path):
        raise AssertionError("a projected read parsed every column")

    def read_tables_keeping(self, path, columns):
        self.kept.append(columns)
        return super().read_tables_keeping(path, columns)


def _registry(reader):
    registry = MetadataRegistry()
    registry.register_reader([".star"], reader)
    registry.register_bundle([".star"], relion4_bundle())
    return registry


def _copy(name, tmp_path):
    return str(shutil.copy(FILES / name, tmp_path / name))


def test_two_columns_read_and_one_changed_write_back_all_of_them(tmp_path):
    source = str(FILES / "one_loop.star")
    result = rxm.read(source, columns=["angle_rot", "angle_tilt"])
    df = result.to_pandas()
    df["angle_rot"] += 10
    out = str(tmp_path / "out.star")

    result.write(out, updates=df)

    before = rxm.read(source).raw.to_pandas()
    after = rxm.read(out).raw.to_pandas()
    assert set(after.columns) == set(before.columns)
    assert after["_rlnAngleRot"].astype(float).tolist() == pytest.approx(
        (before["_rlnAngleRot"].astype(float) + 10).tolist()
    )
    pd.testing.assert_frame_equal(
        rxm.read(out).to_pandas().drop(columns="angle_rot"),
        rxm.read(source).to_pandas().drop(columns="angle_rot"),
    )


def test_a_projection_shows_the_columns_asked_for_in_that_order():
    result = rxm.read(
        str(FILES / "one_loop.star"), columns=["angle_tilt", "image_path"]
    )

    assert result.to_pandas().columns.tolist() == ["angle_tilt", "image_path"]


@pytest.mark.parametrize(
    ("columns", "names"),
    [
        pytest.param(["coord_x"], ("particles",), id="particles"),
        pytest.param(["voltage"], ("optics",), id="optics"),
        pytest.param(
            ["coord_x", "voltage"], ("particles", "optics"), id="both"
        ),
    ],
)
def test_a_projection_names_the_tables_that_declare_a_column(columns, names):
    result = rxm.read(str(FILES / "rln3.1_data_style.star"), columns=columns)

    assert result.names == names


def test_a_column_no_table_declares_raises_before_the_file_is_opened(
    tmp_path,
):
    with pytest.raises(ValueError, match="No canonical table declares 'x'"):
        rxm.read(str(tmp_path / "missing.star"), columns=["x"])


def test_a_column_the_file_does_not_hold_raises():
    result = rxm.read(
        str(FILES / "rln3.1_data_style.star"), columns=["angle_rot"]
    )

    with pytest.raises(ValueError, match="holds no 'angle_rot'"):
        result.to_pandas()


def test_a_view_of_one_table_writes_every_table(tmp_path):
    out = str(tmp_path / "out.star")

    rxm.read(str(FILES / "rln3.1_data_style.star"))["particles"].write(out)

    assert rxm.read(out).names == ("particles", "optics")


def test_updates_of_another_length_raise(tmp_path):
    result = rxm.read(str(FILES / "one_loop.star"), columns=["angle_rot"])
    df = result.to_pandas().head(1)

    with pytest.raises(ValueError, match="one per row rows= keeps"):
        result.write(str(tmp_path / "out.star"), updates=df)


def test_updates_go_to_the_table_the_view_shows(tmp_path):
    result = rxm.read(str(FILES / "rln3.1_data_style.star"))["optics"]
    df = result.to_pandas()
    df["voltage"] = 200.0
    out = str(tmp_path / "out.star")

    result.write(out, updates=df)

    assert rxm.read(out)["optics"].to_pandas()["voltage"].tolist() == [200.0]


def test_updates_may_be_polars(tmp_path):
    result = rxm.read(str(FILES / "one_loop.star"), columns=["angle_psi"])
    df = result.to_polars().with_columns(pl.col("angle_psi") * 0)
    out = str(tmp_path / "out.star")

    result.write(out, updates=df)

    psi = rxm.read(out, columns=["angle_psi"]).to_pandas()["angle_psi"]
    assert set(psi) == {0.0}


def test_a_result_writes_over_its_own_source(tmp_path):
    path = _copy("one_loop.star", tmp_path)
    result = rxm.read(path, columns=["angle_rot"])
    df = result.to_pandas()
    df["angle_rot"] = 1.0

    result.write(path, updates=df)

    assert set(rxm.read(path).to_pandas()["angle_rot"]) == {1.0}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["one_loop.star"]


def test_a_failed_write_leaves_the_destination_as_it_was(tmp_path):
    registry = MetadataRegistry()
    registry.register_reader([".star"], StarReader())
    registry.register_writer([".star"], _Failing())
    registry.register_bundle([".star"], relion4_bundle())
    path = _copy("one_loop.star", tmp_path)
    before = Path(path).read_bytes()
    result = registry.read(path)

    with pytest.raises(RuntimeError, match="disk filled up"):
        result.write(path)

    assert Path(path).read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["one_loop.star"]


def test_the_raw_columns_kept_are_those_read_into_what_was_asked():
    kept = source_columns(["coord_x"], [relion4_bundle()], SCHEMA)

    assert {"_rlnCoordinateX", "_rlnCoordinateY", "_rlnImageName"} <= kept
    assert "_rlnAngleRot" not in kept
    assert "_rlnVoltage" not in kept


def test_a_projected_read_parses_only_the_columns_it_keeps():
    reader = _Spy()
    path = str(FILES / "rln3.1_data_style.star")

    frame = _registry(reader).read(path, columns=["coord_x"]).to_pandas()

    assert reader.kept == [
        source_columns(["coord_x"], [relion4_bundle()], SCHEMA)
    ]
    assert frame["coord_x"].tolist() == (
        rxm.read(path)["particles"].to_pandas()["coord_x"].tolist()
    )


def test_a_reader_that_cannot_narrow_a_read_is_narrowed_after_it():
    path = str(FILES / "rln3.1_data_style.star")
    whole = _Plain().read_tables(path)

    kept = _Plain().read_tables_keeping(
        path, {"_rlnCoordinateX", "_rlnNoSuchColumn"}
    )

    assert [t.schema.table_name for t in kept] == [
        t.schema.table_name for t in whole
    ]
    assert [t.table.num_rows for t in kept] == [
        t.table.num_rows for t in whole
    ]
    assert {n for t in kept for n in t.schema.column_names} == {
        "_rlnCoordinateX"
    }


@pytest.mark.parametrize(
    "name", sorted(p.name for p in FILES.glob("*.star")), ids=str
)
def test_the_parser_keeps_what_a_read_and_a_select_would(name):
    path = str(FILES / name)
    columns = {"_rlnImageName", "_rlnAngleRot", "_rlnVoltage"}

    assert StarReader().read_tables_keeping(path, columns) == (
        _Plain().read_tables_keeping(path, columns)
    )



class _CountingStar(StarReader):
    def __init__(self):
        self.reads = 0

    def read_tables(self, path):
        self.reads += 1
        return super().read_tables(path)


def test_a_canonical_read_keeps_nothing_of_the_file():
    reader = _CountingStar()
    result = rxm.read(str(FILES / "one_loop.star"), reader=reader)

    result["particles"].to_pandas()
    result["particles"].to_pandas()
    result.raw.to_pandas()
    result.raw.to_pandas()

    assert reader.reads == 3
