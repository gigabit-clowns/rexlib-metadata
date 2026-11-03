# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

import rexlib_metadata as rxm
from rexlib_metadata.conventions.cryosparc import Pose
from rexlib_metadata.formats.cryosparc import CsReader

FILES = Path(__file__).parent.parent / "files"
CS = FILES / "cs" / "J114_particles_exported.cs"


@pytest.fixture
def _raw():
    return np.load(CS)


def _relion_matrix(rot, tilt, psi):
    a, b, g = np.radians([rot, tilt, psi])
    ca, sa, cb, sb, cg, sg = (
        np.cos(a), np.sin(a), np.cos(b), np.sin(b), np.cos(g), np.sin(g)
    )
    return np.array(
        [
            [cg * cb * ca - sg * sa, cg * cb * sa + sg * ca, -cg * sb],
            [-sg * cb * ca - cg * sa, -sg * cb * sa + cg * ca, sg * sb],
            [sb * ca, sb * sa, cb],
        ]
    )


def _rodrigues(vector):
    angle = np.linalg.norm(vector)
    if angle == 0:
        return np.eye(3)
    x, y, z = vector / angle
    cross = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return (
        np.eye(3)
        + np.sin(angle) * cross
        + (1 - np.cos(angle)) * cross @ cross
    )


def test_a_cs_file_is_one_table_typed_as_declared():
    reader = CsReader()

    (table,) = reader.read_tables(str(CS))

    assert table.schema.table_name == ""
    assert len(table.table.column_names) == 85
    assert table.table.schema.field("alignments3D/pose").type == (
        pa.list_(pa.float32(), 3)
    )
    assert reader.read_schemas(str(CS)) == [table.schema]


def test_a_cs_file_reads_a_chunk_at_a_time(_raw):
    chunks = list(CsReader().read_chunks(str(CS), 4, {"uid"}))

    assert [len(chunk.table) for _, chunk in chunks] == [4, 4, 2]
    assert chunks[0][1].table.column_names == ["uid"]


def test_the_particles_come_back_canonical(_raw):
    df = rxm.read(str(CS))["particles"].to_pandas()

    paths = [p.decode().removeprefix(">") for p in _raw["blob/path"]]
    assert df["image_path"].tolist() == paths
    assert df["image_index"].tolist() == _raw["blob/idx"].tolist()
    shape = _raw["location/micrograph_shape"]
    expected_x = _raw["location/center_x_frac"].astype(float) * shape[:, 1]
    assert df["coord_x"].tolist() == pytest.approx(expected_x.tolist())


def test_a_pose_becomes_the_angles_of_the_same_rotation(_raw):
    df = rxm.read(str(CS))["particles"].to_pandas()

    for row, pose in enumerate(_raw["alignments3D/pose"].astype(float)):
        angles = df.loc[row, ["angle_rot", "angle_tilt", "angle_psi"]]
        np.testing.assert_allclose(
            _relion_matrix(*angles), _rodrigues(pose), atol=1e-9
        )


@pytest.mark.parametrize(
    "pose",
    [
        pytest.param([0.0, 0.0, 0.0], id="none"),
        pytest.param([0.0, 0.0, 0.7], id="in-plane-only"),
        pytest.param([np.pi, 0.0, 0.0], id="upside-down"),
    ],
)
def test_a_pose_with_no_tilt_or_a_half_turn_is_still_the_rotation(pose):
    column = pa.array([pose], pa.list_(pa.float32(), 3))

    out = Pose().load(pa.table({"alignments3D/pose": column}))

    angles = [out[n][0].as_py() for n in Pose.target_columns]
    np.testing.assert_allclose(
        _relion_matrix(*angles), _rodrigues(np.array(pose)), atol=1e-6
    )


def test_a_pose_comes_back_the_same_whatever_rows_it_is_read_with():
    rng = np.random.default_rng(7)
    poses = pa.array(list(rng.normal(size=(37, 3))), pa.list_(pa.float32()))
    table = pa.table({"alignments3D/pose": poses})

    whole = Pose().load(table)
    alone = [Pose().load(table.slice(row, 1)) for row in range(len(table))]

    for name, column in whole.items():
        rows = [one[name].to_pylist()[0] for one in alone]
        assert column.to_pylist() == rows


def test_a_shift_comes_back_in_angstrom(_raw):
    df = rxm.read(str(CS))["particles"].to_pandas()

    size = _raw["alignments3D/psize_A"].astype(float)
    expected = _raw["alignments3D/shift"][:, 0].astype(float) * size
    assert df["shift_x"].tolist() == pytest.approx(expected.tolist())


def test_the_optics_are_one_row_per_exposure_group_counted_from_one(_raw):
    result = rxm.read(str(CS))

    optics = result["optics"].to_pandas()

    assert _raw["ctf/exp_group_id"].tolist() == [0] * 10
    assert optics["optics_group"].tolist() == [1]
    assert optics["pixel_size"].tolist() == [0.7575]
    assert optics["spherical_aberration"].tolist() == [2.7]
    assert result["particles"].to_pandas()["optics_group"].eq(1).all()


def test_a_cs_file_converts_to_relion(tmp_path):
    source = rxm.read(str(CS))
    out = str(tmp_path / "out.star")

    source.write(out)

    again = rxm.read(out)
    assert again.raw.names == ("optics", "particles")
    for name in source.names:
        pd.testing.assert_frame_equal(
            again[name].to_pandas(), source[name].to_pandas()
        )


@pytest.mark.parametrize(
    "view",
    [
        pytest.param(lambda r: r["particles"], id="particles"),
        pytest.param(lambda r: r["optics"], id="optics"),
        pytest.param(lambda r: r.joined("particles"), id="joined"),
    ],
)
def test_a_cs_file_reads_in_chunks_as_it_reads_whole(view):
    table = view(rxm.read(str(CS)))

    chunks = [chunk.to_arrow() for chunk in table.chunks(3)]

    assert pa.concat_tables(chunks).equals(table.to_arrow())


def test_a_file_that_is_not_a_cs_says_so(tmp_path):
    path = tmp_path / "not.cs"
    path.write_text("data_\n")
    reader = CsReader()

    with pytest.raises(ValueError, match="not a cryoSPARC file"):
        reader.read_tables(str(path))
