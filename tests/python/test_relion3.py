# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

import rexlib_metadata as rxm
from rexlib_metadata import pose
from rexlib_metadata.formats.star import StarReader

from .frames import assert_same

FILES = Path(__file__).parent.parent / "files" / "star"
POLISHED = str(FILES / "relion3.0_polished.star")
MICROGRAPHS = str(FILES / "relion3.0_micrographs.star")


def _pixel_size(raw):
    detector = raw["_rlnDetectorPixelSize"].astype(float)
    return detector * 1e4 / raw["_rlnMagnification"].astype(float)


def test_a_relion30_file_reads_its_optics_from_its_particles():
    result = rxm.read(POLISHED)
    raw = result.raw.to_pandas()

    optics = result["optics"].to_pandas()

    assert result.names == ("particles", "optics")
    assert optics["optics_group"].tolist() == [1]
    assert optics["pixel_size"].tolist() == [_pixel_size(raw)[0]]
    assert optics["voltage"].tolist() == [float(raw["_rlnVoltage"][0])]
    assert result["particles"].to_pandas()["optics_group"].eq(1).all()


def test_a_relion30_offset_in_pixels_comes_back_in_angstrom():
    result = rxm.read(POLISHED)
    raw = result.raw.to_pandas()

    df = result["particles"].to_pandas()

    _, origin = pose.relion(df["transform"])
    expected = raw["_rlnOriginX"].astype(float) * _pixel_size(raw)
    assert origin[0].tolist() == pytest.approx(expected.tolist(), abs=1e-4)


def test_relion30_micrographs_are_one_optics_row():
    optics = rxm.read(MICROGRAPHS)["optics"].to_pandas()

    assert len(optics) == 1


def test_relion30_micrographs_are_a_micrographs_table():
    result = rxm.read(MICROGRAPHS)
    raw = result.raw.to_pandas()

    micrographs = result["micrographs"].to_pandas()

    assert result.names == ("optics", "micrographs")
    assert micrographs["micrograph_path"].tolist() == (
        raw["_rlnMicrographName"].tolist()
    )
    assert micrographs["defocus_u"].tolist() == pytest.approx(
        raw["_rlnDefocusU"].astype(float).tolist()
    )
    assert set(micrographs["optics_group"]) == {1}


def test_a_particles_file_fills_no_micrographs_table():
    assert "micrographs" not in rxm.read(POLISHED).names


def test_relion30_micrographs_write_back_as_relion4(tmp_path):
    source = rxm.read(MICROGRAPHS)
    out = str(tmp_path / "out.star")

    source.write(out)
    again = rxm.read(out)

    assert again.raw.names == ("optics", "micrographs")
    written = again.raw["micrographs"].to_arrow().column_names
    assert "_rlnOpticsGroup" in written
    assert "_rlnCtfImage" in written
    assert "_rlnVoltage" not in written
    for name in source.names:
        assert_same(again[name].to_pandas(), source[name].to_pandas())


def test_a_relion30_file_writes_back_as_relion4(tmp_path):
    source = rxm.read(POLISHED)
    out = str(tmp_path / "out.star")

    source.write(out)

    again = rxm.read(out)
    columns = set(again.raw["particles"].to_pandas().columns)
    assert again.raw.names == ("optics", "particles")
    assert {"_rlnOriginXAngst", "_rlnOpticsGroup", "_rlnClassNumber"} <= columns
    assert not {"_rlnOriginX", "_rlnMagnification", "_rlnVoltage"} & columns
    for name in source.names:
        assert_same(again[name].to_pandas(), source[name].to_pandas())


@pytest.mark.parametrize(
    "view",
    [
        pytest.param(lambda r: r["particles"], id="particles"),
        pytest.param(lambda r: r["optics"], id="optics"),
        pytest.param(lambda r: r.joined("particles"), id="joined"),
    ],
)
def test_a_relion30_file_reads_in_chunks_as_it_reads_whole(view):
    table = view(rxm.read(POLISHED))

    chunks = [chunk.to_arrow() for chunk in table.chunks(2)]

    assert pa.concat_tables(chunks).equals(table.to_arrow())


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("micrographs", id="micrographs"),
        pytest.param("optics", id="optics"),
    ],
)
def test_relion30_micrographs_read_in_chunks_as_they_read_whole(name):
    table = rxm.read(MICROGRAPHS)[name]

    chunks = [chunk.to_arrow() for chunk in table.chunks(2)]

    assert pa.concat_tables(chunks).equals(table.to_arrow())


def test_a_setting_first_held_in_a_later_chunk_keeps_its_number(tmp_path):
    path = _setting_rows(
        tmp_path,
        [
            "1@a.mrcs 300 2.7 0.1 10000 5",
            "2@a.mrcs 200 2.7 0.1 10000 5",
            "3@a.mrcs 300 2.7 0.1 10000 5",
            "4@a.mrcs 100 2.7 0.1 10000 5",
        ],
    )
    result = rxm.read(path)

    groups = [
        chunk.to_pandas()["optics_group"].tolist()
        for chunk in result["particles"].chunks(1)
    ]
    optics = [chunk.to_pandas() for chunk in result["optics"].chunks(1)]

    assert groups == [[1], [2], [1], [3]]
    assert pd.concat(optics)["voltage"].tolist() == [300.0, 200.0, 100.0]


class _Recording(StarReader):
    def __init__(self):
        self.asked = []

    def read_chunks(self, path, size, columns=None):
        self.asked.append(None if columns is None else set(columns))
        return super().read_chunks(path, size, columns)


def test_the_groups_are_gathered_from_their_columns_alone():
    reader = _Recording()
    registry = rxm.new_registry()
    result = registry.read(POLISHED, reader=reader)

    list(result["particles"].chunks(5))

    setting = {
        "_rlnVoltage",
        "_rlnSphericalAberration",
        "_rlnAmplitudeContrast",
        "_rlnMagnification",
        "_rlnDetectorPixelSize",
    }
    assert setting in reader.asked


def _setting_rows(tmp_path, rows):
    header = (
        "data_\n\nloop_\n_rlnImageName\n_rlnVoltage\n_rlnSphericalAberration\n"
        "_rlnAmplitudeContrast\n_rlnMagnification\n_rlnDetectorPixelSize\n"
    )
    path = tmp_path / "settings.star"
    path.write_text(header + "".join(f"{row}\n" for row in rows))
    return str(path)


def test_each_distinct_setting_is_a_group_numbered_as_first_held(tmp_path):
    path = _setting_rows(
        tmp_path,
        [
            "1@a.mrcs 200 2.7 0.1 10000 5",
            "2@a.mrcs 300 2.7 0.1 10000 5",
            "3@a.mrcs 200 2.7 0.1 10000 5",
        ],
    )
    result = rxm.read(path)

    particles = result["particles"].to_pandas()
    optics = result["optics"].to_pandas()

    assert particles["optics_group"].tolist() == [1, 2, 1]
    assert optics["optics_group"].tolist() == [1, 2]
    assert optics["voltage"].tolist() == [200.0, 300.0]


def _relion30(tmp_path, detector, origin):
    path = tmp_path / "r30.star"
    names = ["_rlnImageName", "_rlnAnglePsi", "_rlnOriginX", "_rlnOriginY"]
    row = ["1@a.mrcs", "30", origin, "0"]
    if detector is not None:
        names += [
            "_rlnVoltage",
            "_rlnSphericalAberration",
            "_rlnAmplitudeContrast",
            "_rlnMagnification",
            "_rlnDetectorPixelSize",
        ]
        row += ["300", "2.7", "0.1", "10000", detector]
    header = "".join(f"{name}\n" for name in names)
    path.write_text(f"data_\nloop_\n{header}{' '.join(row)}\n")
    return str(path)


def test_an_origin_in_pixels_with_no_detector_is_refused(tmp_path):
    view = rxm.read(_relion30(tmp_path, detector=None, origin="2"))

    with pytest.raises(ValueError, match="_rlnDetectorPixelSize"):
        view["particles"].to_arrow()


def test_an_origin_with_no_finite_pixel_size_is_refused(tmp_path):
    view = rxm.read(_relion30(tmp_path, detector='""', origin="2"))

    with pytest.raises(ValueError, match=r"_rlnOriginX is 2\.0 px in row 0"):
        view["particles"].to_arrow()


def test_a_zero_origin_needs_no_pixel_size(tmp_path):
    path = _relion30(tmp_path, detector='""', origin="0")

    df = rxm.read(path)["particles"].to_pandas()

    assert pose.matrices(df["transform"])[0, :, 3].tolist() == [0, 0, 0]


def test_a_setting_written_two_ways_is_one_group(tmp_path):
    path = tmp_path / "r30.star"
    path.write_text(
        "data_\nloop_\n_rlnImageName\n_rlnVoltage\n_rlnSphericalAberration\n"
        "_rlnAmplitudeContrast\n_rlnMagnification\n_rlnDetectorPixelSize\n"
        "1@a.mrcs 300 2.7 0.1 10000 5\n2@a.mrcs 300.0 2.70 0.10 10000 5.0\n"
    )

    groups = rxm.read(str(path))["particles"].to_pandas()["optics_group"]

    assert groups.tolist() == [1, 1]


def test_relion30_micrographs_keep_their_defocus_angle():
    result = rxm.read(MICROGRAPHS)
    raw = result.raw.to_pandas()

    micrographs = result["micrographs"].to_pandas()

    assert micrographs["defocus_angle"].tolist() == pytest.approx(
        raw["_rlnDefocusAngle"].astype(float).tolist()
    )


def test_joined_micrographs_carry_their_optics_on_each_row():
    result = rxm.read(MICROGRAPHS)
    micrographs = result["micrographs"].to_pandas()
    (optics,) = result["optics"].to_pandas().to_dict("records")

    joined = result.joined("micrographs").to_pandas()

    assert_same(joined[micrographs.columns], micrographs)
    for name, value in optics.items():
        assert joined[name].tolist() == [value] * len(micrographs)
