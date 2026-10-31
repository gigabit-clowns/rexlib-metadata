# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import pytest

import rexlib_metadata as rxm
from rexlib_metadata.canonical import PARTICLES
from rexlib_metadata.convention import ConventionBundle, ReadConvention
from rexlib_metadata.conventions.relion import relion4_bundle, split_reference
from rexlib_metadata.engine import read_canonical

FILES = Path(__file__).parent.parent / "files" / "star"


def canonical(file, table):
    return rxm.read(str(FILES / file))[table].to_pandas()


def test_a_relion_file_is_read_without_being_told_what_it_is():
    assert rxm.read(str(FILES / "rln3.1_data_style.star")).names == (
        "particles",
        "optics",
    )


def test_a_relion_particle_table_becomes_canonical():
    df = canonical("rln3.1_data_style.star", "particles")

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
    df = canonical("one_loop.star", "particles")

    assert df["image_index"].tolist() == [0] * 16
    assert df["image_path"][0].endswith("tomo_ts01.mrc_0000000_5.00A.mrc")


def test_the_angles_and_the_resolution_come_through_as_numbers():
    df = canonical("one_loop.star", "particles")

    assert df["angle_rot"].tolist() == [0.0] * 16
    assert df["ctf_max_resolution"][0] == pytest.approx(7.4)
    assert str(df["angle_rot"].dtype) == "float64"


def test_the_shifts_come_through_in_angstrom():
    df = canonical("relion3.1_subtomo.star", "particles")

    assert df["shift_x"][0] == pytest.approx(3.947427)
    assert df["shift_y"][1] == pytest.approx(5.447427)
    assert df["shift_z"][1] == pytest.approx(1.947427)
    assert str(df["shift_z"].dtype) == "float64"


def test_a_relion_optics_table_becomes_canonical():
    df = canonical("rln3.1_data_style.star", "optics")

    assert df["optics_group"][0] == 1
    assert df["voltage"][0] == 300.0
    assert df["spherical_aberration"][0] == 2.7
    assert df["pixel_size"][0] == pytest.approx(1.04)
    assert df["image_size"][0] == 400
    assert df["image_dimensionality"][0] == 2


def test_a_column_nobody_wrote_is_left_out():
    df = canonical("rln3.1_data_style.star", "particles")

    assert "angle_rot" not in df.columns
    assert "optics_group" not in df.columns


def test_a_convention_of_another_table_is_never_offered_this_one():
    class Exploding(ReadConvention):
        target_columns = ("voltage",)

        def matches(self, raw):
            return True

        def load(self, table):
            raise AssertionError("load was called")

    bundle = ConventionBundle(
        "mylab",
        {
            "particles": relion4_bundle().read_conventions("particles"),
            "optics": [Exploding()],
        },
    )
    tables = rxm.read(str(FILES / "rln3.1_data_style.star")).raw.tables()

    df = read_canonical(tables, [bundle], PARTICLES).to_pandas()

    assert "image_path" in df.columns
    assert "voltage" not in df.columns


def test_a_bundle_of_your_own_replaces_the_registered_ones():
    result = rxm.read(
        str(FILES / "rln3.1_data_style.star"), bundle=ConventionBundle("empty")
    )

    assert result.names == ()


def test_a_file_no_convention_understands_says_so():
    result = rxm.read(str(FILES / "postprocess.star"))

    assert result.names == ()
    with pytest.raises(ValueError, match=r"through \.raw"):
        result.to_pandas()


def test_a_file_of_rows_that_a_bundle_misreads_is_not_an_empty_table():
    tables = rxm.read(str(FILES / "one_loop.star")).raw.tables()
    nothing = ConventionBundle("empty")

    with pytest.raises(ValueError, match="understood a single column"):
        read_canonical(tables, [nothing], PARTICLES)


def test_the_canonical_view_and_the_file_view_are_both_there():
    result = rxm.read(str(FILES / "one_loop.star"))

    assert "image_path" in result["particles"].to_pandas().columns
    assert "_rlnImageName" in result.raw["particles"].to_pandas().columns


REFERENCES = [
    "000012@Extract/a.mrcs",
    "a.mrcs",
    "abc@x.mrcs",
    "@x",
    "1@2@3",
    "",
    "٣@x",
    "007@",
    "123",
    "1a@b",
    None,
]


@pytest.mark.parametrize("reference", REFERENCES)
def test_a_reference_splits_as_the_pattern_it_replaced_did(reference):
    pa = pytest.importorskip("pyarrow")
    pc = pytest.importorskip("pyarrow.compute")
    column = pa.chunked_array([[reference]], pa.string())
    parts = pc.extract_regex(column, r"^(?:(?P<index>[0-9]+)@)?(?P<path>.*)$")
    written = pc.struct_field(parts, "index")
    expected_index = pc.if_else(pc.equal(written, ""), "1", written)

    index, path = split_reference(column)

    assert index.to_pylist() == expected_index.to_pylist()
    assert path.to_pylist() == pc.struct_field(parts, "path").to_pylist()


def test_a_value_that_does_not_parse_names_the_file_and_the_table(tmp_path):
    path = tmp_path / "broken.star"
    path.write_text(
        "data_particles\nloop_\n_rlnImageName\n_rlnCoordinateX\n"
        "_rlnCoordinateY\n2@a.mrcs abc 3\n"
    )
    particles = rxm.read(str(path))["particles"]

    with pytest.raises(ValueError, match=r"broken\.star.*'particles'.*abc"):
        particles.to_pandas()
    with pytest.raises(ValueError, match="does not parse"):
        next(particles.chunks(1))
