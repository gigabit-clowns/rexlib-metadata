from pathlib import Path

import pytest

import rexlib_metadata as rxm
from rexlib_metadata.canonical import OPTICS, PARTICLES
from rexlib_metadata.conventions.relion import optics_bundle, particles_bundle
from rexlib_metadata.engine import read_canonical

FILES = Path(__file__).parent.parent / "files" / "star"


def canonical(file, table, schema, bundle):
    raw = rxm.read(str(FILES / file))[table]
    return read_canonical(raw._materialize(), [bundle], schema).to_pandas()


def test_a_relion_particle_table_becomes_canonical():
    df = canonical(
        "rln3.1_data_style.star", "block_2", PARTICLES, particles_bundle()
    )

    assert list(df.columns) == [
        "image_path",
        "image_index",
        "micrograph_path",
        "coord_x",
        "coord_y",
        "coord_z",
    ]
    assert df["image_path"][0] == "0001_sum_particles.mrcs"
    assert df["image_index"][0] == 0
    assert df["coord_x"].tolist() == [587.0, 685.0]


def test_a_bare_path_is_an_image_reference_too():
    df = canonical("one_loop.star", "particles", PARTICLES, particles_bundle())

    assert df["image_index"].tolist() == [0] * 16
    assert df["image_path"][0].endswith("tomo_ts01.mrc_0000000_5.00A.mrc")


def test_the_angles_and_the_resolution_come_through_as_numbers():
    df = canonical("one_loop.star", "particles", PARTICLES, particles_bundle())

    assert df["angle_rot"].tolist() == [0.0] * 16
    assert df["ctf_max_resolution"][0] == pytest.approx(7.4)
    assert str(df["angle_rot"].dtype) == "float64"


def test_a_relion_optics_table_becomes_canonical():
    df = canonical("rln3.1_data_style.star", "block_1", OPTICS, optics_bundle())

    assert df["optics_group"][0] == 1
    assert df["voltage"][0] == 300.0
    assert df["spherical_aberration"][0] == 2.7
    assert df["pixel_size"][0] == pytest.approx(1.04)
    assert df["image_size"][0] == 400
    assert df["image_dimensionality"][0] == 2


def test_a_column_nobody_wrote_is_left_out():
    df = canonical(
        "rln3.1_data_style.star", "block_2", PARTICLES, particles_bundle()
    )

    assert "angle_rot" not in df.columns
    assert "optics_group" not in df.columns


def test_the_optics_bundle_does_not_claim_a_particle_table():
    raw = rxm.read(str(FILES / "rln3.1_data_style.star"))["block_2"]

    table = raw._materialize()
    bundles = [optics_bundle()]

    with pytest.raises(ValueError, match="requires"):
        read_canonical(table, bundles, OPTICS)
