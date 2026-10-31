# SPDX-License-Identifier: LGPL-2.1-or-later

import math
import shutil
from pathlib import Path

import pyarrow as pa
import pytest

import rexlib_metadata as rxm
from rexlib_metadata.convention import ConventionBundle
from rexlib_metadata.conventions.relion import (
    WriteImageReference,
    relion4_bundle,
)
from rexlib_metadata.conventions.star import StarWriter

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


def test_an_in_plane_angle_reads_on_its_own(tmp_path):
    df = rxm.read(psi_only(tmp_path))["particles"].to_pandas()

    assert df["angle_psi"].tolist() == [10.0, 20.0]
    assert "angle_rot" not in df.columns


def test_an_update_to_an_angle_on_its_own_reaches_the_file(tmp_path):
    out = tmp_path / "out.star"
    particles = rxm.read(psi_only(tmp_path))["particles"]

    particles.write(str(out), updates=pa.table({"angle_psi": [99.0, 98.0]}))

    again = rxm.read(str(out))["particles"].to_pandas()
    assert again["angle_psi"].tolist() == [99.0, 98.0]


def test_an_update_no_convention_writes_raises(tmp_path):
    images = ConventionBundle(
        "images", write={"particles": [WriteImageReference()]}
    )
    particles = rxm.read(psi_only(tmp_path))["particles"]
    updates = pa.table({"angle_psi": [99.0, 98.0]})
    out = str(tmp_path / "out.star")

    with pytest.raises(ValueError, match="'angle_psi'"):
        particles.write(out, bundle=images, updates=updates)


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
    updates = particles.to_pandas()[["shift_x"]]
    updates.loc[0, "shift_x"] = math.nan

    particles.write(str(out), updates=updates)

    again = rxm.read(str(out))["particles"].to_pandas()
    assert math.isnan(again["shift_x"][0])
    assert again["shift_x"][1] == updates["shift_x"][1]


def test_an_empty_number_in_a_file_reads_as_missing(tmp_path):
    path = tmp_path / "empty.star"
    path.write_text(PSI_ONLY.replace("10.0 1.0", '"" 1.0'))

    df = rxm.read(str(path))["particles"].to_pandas()

    assert math.isnan(df["angle_psi"][0])
    assert df["angle_psi"][1] == 20.0
