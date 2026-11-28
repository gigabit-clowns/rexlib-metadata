# SPDX-License-Identifier: LGPL-2.1-or-later

import os
import stat
from pathlib import Path

import pandas as pd
import polars as pl
import pyarrow as pa
import pytest

import rexlib_metadata as rxm
from rexlib_metadata import pose
from rexlib_metadata.convention import ConventionBundle
from rexlib_metadata.conventions.relion import Pose, relion4_bundle
from rexlib_metadata.formats.star import StarReader, StarWriter

from .frames import assert_same

FILES = Path(__file__).parent.parent / "files" / "star"
SUBTOMO = str(FILES / "relion3.1_subtomo.star")


class MovedPose(Pose):
    def offsets(self, table):
        x, y, z = super().offsets(table)
        return x + 1.0, y, z


def mylab():
    return ConventionBundle("mylab", read={"particles": [MovedPose()]})


def test_a_bundle_of_your_own_goes_in_front_of_relions():
    plain = rxm.read(SUBTOMO)["particles"].to_pandas()

    layered = rxm.read(SUBTOMO, bundle=[mylab(), relion4_bundle()])
    df = layered["particles"].to_pandas()

    a, origin = pose.relion(df["transform"])
    plain_a, plain_origin = pose.relion(plain["transform"])
    assert origin[0] == pytest.approx(plain_origin[0] + 1.0, abs=1e-5)
    assert a[0][0] == pytest.approx(plain_a[0][0])
    assert df["coord_x"].tolist() == plain["coord_x"].tolist()


def test_a_write_takes_several_bundles_too(tmp_path):
    out = tmp_path / "out.star"
    source = rxm.read(SUBTOMO)

    source.write(str(out), bundle=[mylab(), relion4_bundle()])

    assert_same(
        rxm.read(str(out))["particles"].to_pandas(),
        source["particles"].to_pandas(),
    )


def test_frames_read_from_a_file_write_back_the_same(tmp_path):
    out = str(tmp_path / "out.star")
    source = rxm.read(SUBTOMO)
    tables = {name: source[name].to_pandas() for name in source.names}

    rxm.write(out, tables)

    again = rxm.read(out)
    for name, frame in tables.items():
        assert_same(again[name].to_pandas(), frame)


def test_frames_built_in_memory_write_a_star_file(tmp_path):
    out = str(tmp_path / "picked.star")
    particles = pd.DataFrame(
        {
            "image_path": ["stack.mrcs", "stack.mrcs"],
            "image_index": [0, 1],
            "coord_x": [100.0, 200.0],
            "coord_y": [50.0, 75.0],
        }
    )

    rxm.write(out, {"particles": particles})

    again = rxm.read(out)["particles"].to_pandas()
    assert again["coord_x"].tolist() == [100.0, 200.0]
    assert rxm.read(out).raw.to_pandas()["_rlnImageName"].tolist() == [
        "000001@stack.mrcs",
        "000002@stack.mrcs",
    ]


def test_polars_frames_write_as_well(tmp_path):
    out = str(tmp_path / "out.star")
    particles = pl.DataFrame({"image_path": ["a.mrcs"], "image_index": [0]})

    rxm.write(out, {"particles": particles})

    again = rxm.read(out)["particles"].to_polars()
    assert again.select(particles.columns).equals(particles)


def test_frames_with_optics_reach_a_format_with_no_optics_table(tmp_path):
    out = str(tmp_path / "out.xmd")
    source = rxm.read(SUBTOMO)
    tables = {name: source[name].to_pandas() for name in source.names}

    rxm.write(out, tables)

    again = rxm.read(out)["particles"].to_pandas()
    reference = ["image_path", "image_index"]
    assert_same(again[reference], tables["particles"][reference])


@pytest.mark.parametrize(
    ("tables", "error", "message"),
    [
        ({"particle": pd.DataFrame()}, KeyError, "No canonical table"),
        (
            {
                "particles": pd.DataFrame(
                    {"image_path": ["a"], "image_index": [0], "nope": [1]}
                )
            },
            ValueError,
            "holds 'nope', which no table of 'particles' declares",
        ),
        (
            {
                "particles": pd.DataFrame(
                    {"image_path": ["a"], "image_index": ["first"]}
                )
            },
            ValueError,
            "'image_index' holds a value its declared type, int64, cannot",
        ),
        (
            {"particles": pd.DataFrame({"coord_x": [1.0]})},
            ValueError,
            "requires 'image_path', 'image_index'",
        ),
        ({}, ValueError, "no table was given"),
    ],
)
def test_frames_that_are_not_canonical_are_refused(
    tmp_path, tables, error, message
):
    out = str(tmp_path / "out.star")

    with pytest.raises(error, match=message):
        rxm.write(out, tables)


def test_a_joined_view_writes_its_own_columns_back(tmp_path):
    out = tmp_path / "out.star"
    source = rxm.read(SUBTOMO)
    view = source.joined("particles")
    flat = view.to_pandas()
    flat["coord_x"] += 1.0

    view.updated(flat).write(str(out))

    again = rxm.read(str(out))
    moved = again["particles"].to_pandas()["coord_x"].tolist()
    assert moved == pytest.approx(flat["coord_x"].tolist())
    assert_same(again["optics"].to_pandas(), source["optics"].to_pandas())


def test_a_joined_view_refuses_a_change_to_the_table_it_points_at(tmp_path):
    view = rxm.read(SUBTOMO).joined("particles")
    flat = view.to_pandas()
    flat["pixel_size"] = 6.0
    out = str(tmp_path / "out.star")

    with pytest.raises(ValueError, match="'pixel_size'"):
        view.updated(flat).write(out)


_POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")


@_POSIX_ONLY
def test_a_file_written_over_keeps_its_mode(tmp_path):
    out = tmp_path / "out.star"
    out.write_text("")
    out.chmod(0o640)

    rxm.read(SUBTOMO).write(str(out))

    assert stat.S_IMODE(out.stat().st_mode) == 0o640


@_POSIX_ONLY
def test_a_new_file_takes_a_new_files_mode(tmp_path):
    out = tmp_path / "out.star"
    umask = os.umask(0)
    os.umask(umask)

    rxm.read(SUBTOMO).write(str(out))

    assert stat.S_IMODE(out.stat().st_mode) == 0o666 & ~umask


def test_arrow_tables_write_as_well(tmp_path):
    out = str(tmp_path / "out.star")
    particles = pa.table(
        {"image_path": ["a.mrcs", "a.mrcs"], "image_index": [0, 1]}
    )

    rxm.write(out, {"particles": particles})

    again = rxm.read(out)["particles"].to_arrow()
    assert again.column("image_index").to_pylist() == [0, 1]


def test_frames_write_through_the_writer_and_bundle_named(tmp_path):
    out = str(tmp_path / "out.txt")
    source = rxm.read(SUBTOMO)
    tables = {name: source[name].to_pandas() for name in source.names}

    rxm.write(out, tables, writer=StarWriter(), bundle=relion4_bundle())

    again = rxm.read(out, reader=StarReader(), bundle=relion4_bundle())
    for name, frame in tables.items():
        assert_same(again[name].to_pandas(), frame)


def test_frames_to_an_extension_with_no_writer_are_refused(tmp_path):
    frame = pd.DataFrame({"image_path": ["a.mrcs"], "image_index": [0]})

    with pytest.raises(ValueError, match=r"No writer registered for '\.txt'"):
        rxm.write(str(tmp_path / "out.txt"), {"particles": frame})
