# SPDX-License-Identifier: LGPL-2.1-or-later

import numpy as np
import pandas as pd
import polars as pl
import pyarrow as pa
import pytest

from rexlib_metadata import pose


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


def _one(values):
    return tuple(np.array([value], dtype=np.float64) for value in values)


def _transform(angles, origin):
    return pose.transforms(pose.euler_matrix(*_one(angles)), _one(origin))


def test_a_transform_is_the_inverse_of_relions_projection():
    angles, origin = (30.0, 50.0, 70.0), (1.5, -2.0, 0.7)

    got = pose.matrices(_transform(angles, origin))[0]

    projection = np.eye(4)
    projection[:3, :3] = _relion_matrix(*angles)
    projection[:3, 3] = -np.array(origin)
    np.testing.assert_allclose(got, np.linalg.inv(projection)[:3], atol=1e-6)


def test_relions_angles_and_origin_come_back():
    angles, origin = (30.0, 50.0, 70.0), (1.5, -2.0, 0.7)

    a, offsets = pose.relion(_transform(angles, origin))

    got = [angle[0] for angle in pose.euler_angles(a)]
    assert got == pytest.approx(angles, abs=1e-4)
    assert [x[0] for x in offsets] == pytest.approx(origin, abs=1e-5)


@pytest.mark.parametrize(
    ("angles", "expected"),
    [
        pytest.param((30.0, 0.0, 20.0), (0.0, 0.0, 50.0), id="untilted"),
        pytest.param((30.0, 180.0, 20.0), (0.0, 180.0, -10.0), id="upside"),
    ],
)
def test_without_a_tilt_the_turn_is_psis(angles, expected):
    turned = pose.euler_angles(pose.euler_matrix(*_one(angles)))

    got = [angle[0] for angle in turned]
    assert got == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize(
    "scale",
    [
        pytest.param((2.0, 1.0, 1.0), id="scaled"),
        pytest.param((-1.0, 1.0, 1.0), id="mirrored"),
    ],
)
def test_a_transform_that_is_no_rotation_has_no_angles(scale):
    a = tuple(
        tuple(np.array([factor if i == j else 0.0]) for j in range(3))
        for i, factor in enumerate(scale)
    )

    with pytest.raises(ValueError, match="row 0"):
        pose.check_rotation(a)


def test_a_null_transform_is_nan_and_passes_as_a_rotation():
    column = pa.array([None], pose.TRANSFORM)

    a, _ = pose.relion(column)

    assert np.isnan(pose.matrices(column)).all()
    pose.check_rotation(a)


@pytest.mark.parametrize(
    "holder",
    [
        pytest.param(lambda column: column, id="arrow"),
        pytest.param(lambda column: column.to_pandas(), id="pandas"),
        pytest.param(pl.from_arrow, id="polars"),
    ],
)
def test_a_column_is_read_whoever_holds_it(holder):
    column = _transform((30.0, 50.0, 70.0), (1.5, -2.0, 0.7))

    got = pose.matrices(holder(column))

    np.testing.assert_array_equal(got, pose.matrices(column))


def test_a_transform_comes_back_the_same_whatever_rows_it_is_built_with():
    rng = np.random.default_rng(7)
    angles = tuple(rng.uniform(-180, 180, size=37) for _ in range(3))
    origin = tuple(rng.normal(size=37) for _ in range(3))

    whole = pose.transforms(pose.euler_matrix(*angles), origin)

    for row in range(37):
        one = tuple(a[row : row + 1] for a in angles)
        alone = pose.transforms(
            pose.euler_matrix(*one), tuple(o[row : row + 1] for o in origin)
        )
        assert alone.to_pylist() == whole.slice(row, 1).to_pylist()


def test_a_frame_of_lists_casts_to_the_canonical_column():
    frame = pd.DataFrame({"transform": [list(range(12))]})

    got = pose.matrices(frame["transform"])

    assert got.tolist() == [[[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]]]
