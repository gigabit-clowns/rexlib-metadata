# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import pandas as pd
import polars as pl
import pyarrow as pa
import pyarrow.compute as pc
import pytest

import rexlib_metadata as rxm
from rexlib_metadata.convention import ConventionBundle
from rexlib_metadata.conventions.relion import AngleRot, relion4_bundle

FILES = Path(__file__).parent.parent / "files" / "star"
SUBTOMO = str(FILES / "relion3.1_subtomo.star")


class TurnedAngleRot(AngleRot):
    def load(self, table):
        (column,) = super().load(table).values()
        return {"angle_rot": pc.add(column, pa.scalar(90.0))}


def mylab():
    return ConventionBundle("mylab", read={"particles": [TurnedAngleRot()]})


def test_a_bundle_of_your_own_goes_in_front_of_relions():
    plain = rxm.read(SUBTOMO)["particles"].to_pandas()

    layered = rxm.read(SUBTOMO, bundle=[mylab(), relion4_bundle()])
    df = layered["particles"].to_pandas()

    assert df["angle_rot"].tolist() == (plain["angle_rot"] + 90).tolist()
    assert df["shift_x"].tolist() == plain["shift_x"].tolist()


def test_a_write_takes_several_bundles_too(tmp_path):
    out = tmp_path / "out.star"

    rxm.read(SUBTOMO).write(str(out), bundle=[mylab(), relion4_bundle()])

    assert len(rxm.read(str(out))["particles"].to_pandas()) == 57


def test_frames_read_from_a_file_write_back_the_same(tmp_path):
    out = str(tmp_path / "out.star")
    source = rxm.read(SUBTOMO)
    tables = {name: source[name].to_pandas() for name in source.names}

    rxm.write(out, tables)

    again = rxm.read(out)
    for name, frame in tables.items():
        pd.testing.assert_frame_equal(again[name].to_pandas(), frame)


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

    assert len(rxm.read(out)["particles"].to_pandas()) == 1


def test_frames_with_optics_reach_a_format_with_no_optics_table(tmp_path):
    out = str(tmp_path / "out.xmd")
    source = rxm.read(SUBTOMO)
    tables = {name: source[name].to_pandas() for name in source.names}

    rxm.write(out, tables)

    assert len(rxm.read(out)["particles"].to_pandas()) == 57


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
            "declares no 'nope'",
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
    view = rxm.read(SUBTOMO).joined("particles")
    flat = view.to_pandas()
    flat["angle_rot"] += 1.0

    view.write(str(out), updates=flat)

    again = rxm.read(str(out))
    turned = again["particles"].to_pandas()["angle_rot"].tolist()
    assert turned == pytest.approx(flat["angle_rot"].tolist())
    assert again["optics"].to_pandas()["pixel_size"].tolist() == [5.0]


def test_a_joined_view_refuses_a_change_to_the_table_it_points_at(tmp_path):
    view = rxm.read(SUBTOMO).joined("particles")
    flat = view.to_pandas()
    flat["pixel_size"] = 6.0
    out = str(tmp_path / "out.star")

    with pytest.raises(ValueError, match="'pixel_size'"):
        view.write(out, updates=flat)
