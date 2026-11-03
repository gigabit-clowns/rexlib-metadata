# SPDX-License-Identifier: LGPL-2.1-or-later

import math
import shutil
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

import rexlib_metadata as rxm
from rexlib_metadata import pose
from rexlib_metadata.convention import ConventionBundle
from rexlib_metadata.conventions.relion import (
    WriteImageReference,
    relion4_bundle,
)
from rexlib_metadata.formats.star import StarWriter

STAR = Path(__file__).parent.parent / "files" / "star"

PSI_ONLY = """data_particles

loop_
_rlnImageName
_rlnAnglePsi
_rlnOriginXAngst
_rlnOriginYAngst
000001@a.mrcs 10.0 1.0 2.0
000002@a.mrcs 20.0 3.0 4.0
"""


def frames(result):
    return {name: result[name].to_pandas() for name in result.names}


def psi_only(tmp_path):
    path = tmp_path / "psi.star"
    path.write_text(PSI_ONLY)
    return str(path)


def test_blocks_no_convention_fills_reach_a_file_of_the_same_format(tmp_path):
    out = tmp_path / "out.star"
    source = rxm.read(str(STAR / "postprocess.star"))

    source.write(str(out))
    again = rxm.read(str(out)).raw

    assert again.names == ("general", "fsc", "guinier")
    for name, frame in frames(source.raw).items():
        assert again[name].to_pandas().equals(frame)


def test_a_file_written_over_itself_keeps_every_block(tmp_path):
    path = tmp_path / "postprocess.star"
    shutil.copy(STAR / "postprocess.star", path)

    rxm.read(str(path)).write(str(path))

    assert rxm.read(str(path)).raw.names == ("general", "fsc", "guinier")


def test_a_second_block_of_particles_is_not_lost(tmp_path):
    out = tmp_path / "out.star"

    rxm.read(str(STAR / "rln3.1_data_style.star")).write(str(out))

    assert "block_3" in rxm.read(str(out)).raw.names


def test_a_write_that_would_hold_nothing_raises_and_leaves_the_file(tmp_path):
    out = tmp_path / "out.xmd"
    out.write_text("kept")
    source = rxm.read(str(STAR / "postprocess.star"))

    with pytest.raises(ValueError, match="Nothing of"):
        source.write(str(out))
    assert out.read_text() == "kept"


def _turned(psi):
    zero = np.zeros(len(psi))
    a = pose.euler_matrix(zero, zero, np.array(psi))
    return pa.table({"transform": pose.transforms(a, (zero, zero, zero))})


def test_an_in_plane_angle_reads_on_its_own(tmp_path):
    df = rxm.read(psi_only(tmp_path))["particles"].to_pandas()

    rot, tilt, psi = pose.euler(df["transform"])

    assert psi.tolist() == pytest.approx([10.0, 20.0])
    assert rot.tolist() == tilt.tolist() == [0.0, 0.0]


def test_an_update_to_a_pose_reaches_the_file(tmp_path):
    out = tmp_path / "out.star"
    particles = rxm.read(psi_only(tmp_path))["particles"]

    particles.write(str(out), updates=_turned([99.0, 98.0]))

    again = rxm.read(str(out)).raw["particles"].to_pandas()
    assert again["_rlnAnglePsi"].tolist() == ["99", "98"]
    assert again["_rlnOriginXAngst"].tolist() == ["0", "0"]


def test_an_update_no_convention_writes_raises(tmp_path):
    images = ConventionBundle(
        "images", write={"particles": [WriteImageReference()]}
    )
    particles = rxm.read(psi_only(tmp_path))["particles"]
    out = str(tmp_path / "out.star")

    with pytest.raises(ValueError, match="'transform'"):
        particles.write(out, bundle=images, updates=_turned([99.0, 98.0]))


def test_two_extensions_of_one_writer_are_one_format(tmp_path):
    source = tmp_path / "s.sqlite"
    rxm.read(str(STAR / "relion3.1_subtomo.star")).raw.write(str(source))
    relion = relion4_bundle()

    rxm.read(str(source), bundle=relion).write(
        str(tmp_path / "t.db"), bundle=relion
    )

    again = rxm.read(str(tmp_path / "t.db")).raw["particles"].to_pandas()
    assert len(again.columns) == 22


def test_a_writer_named_as_the_registered_one_is_the_same_format(tmp_path):
    out = tmp_path / "out.star"

    rxm.read(str(STAR / "one_loop.star")).write(str(out), writer=StarWriter())

    assert "_rlnCtfImage" in rxm.read(str(out)).raw.to_pandas().columns


def test_a_missing_number_survives_a_round_trip(tmp_path):
    out = tmp_path / "out.star"
    particles = rxm.read(str(STAR / "relion3.1_subtomo.star"))["particles"]
    updates = particles.to_pandas()[["coord_x"]]
    updates.loc[0, "coord_x"] = math.nan

    particles.write(str(out), updates=updates)

    again = rxm.read(str(out))["particles"].to_pandas()
    assert math.isnan(again["coord_x"][0])
    assert again["coord_x"][1] == updates["coord_x"][1]


def test_an_empty_angle_in_a_file_is_no_turn(tmp_path):
    path = tmp_path / "empty.star"
    path.write_text(PSI_ONLY.replace("10.0 1.0", '"" 1.0'))

    df = rxm.read(str(path))["particles"].to_pandas()

    _, _, psi = pose.euler(df["transform"])
    assert psi.tolist() == pytest.approx([0.0, 20.0])


def test_a_null_pose_is_written_empty(tmp_path):
    out = tmp_path / "out.star"
    particles = rxm.read(psi_only(tmp_path))["particles"]
    updates = _turned([99.0, 98.0])
    nulled = pa.array([None, updates.column(0)[1].as_py()], pose.TRANSFORM)

    particles.write(str(out), updates=pa.table({"transform": nulled}))

    again = rxm.read(str(out)).raw["particles"].to_pandas()
    assert again["_rlnAnglePsi"].tolist() == ["", "98"]
