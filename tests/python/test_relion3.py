# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import pandas as pd
import pytest

import rexlib_metadata as rxm

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

    expected = raw["_rlnOriginX"].astype(float) * _pixel_size(raw)
    assert df["shift_x"].tolist() == pytest.approx(expected.tolist())


def test_relion30_micrographs_are_one_optics_row():
    optics = rxm.read(MICROGRAPHS)["optics"].to_pandas()

    assert len(optics) == 1


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
        pd.testing.assert_frame_equal(
            again[name].to_pandas(), source[name].to_pandas()
        )


def test_a_relion30_file_is_not_read_a_chunk_at_a_time():
    particles = rxm.read(POLISHED)["particles"]

    with pytest.raises(ValueError, match="read it whole"):
        next(particles.chunks(5))


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
