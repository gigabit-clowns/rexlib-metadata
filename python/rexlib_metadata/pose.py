# SPDX-License-Identifier: LGPL-2.1-or-later

"""The canonical pose: one 3x4 transform per particle.

`transform` is `[R | t]`, row by row, taking a point of the particle's
frame into the reference's, as Scipion's projection alignment does. `R`
is the transpose of the matrix `A` Relion builds from its ZYZ angles, and
`t` is `R` times Relion's origin, in Ångström. Every step is one element
at a time, so a row's result does not depend on the rows converted with
it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pyarrow as pa
import pyarrow.compute as pc

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    import numpy as np
    import pandas as pd
    import polars as pl

    from rexlib_metadata.convention import ArrowColumn

    Transforms = ArrowColumn | pd.Series | pl.Series | Sequence[Sequence[float]]
    Matrix = tuple[tuple[np.ndarray, ...], ...]
    Vector = tuple[np.ndarray, ...]

TRANSFORM = pa.list_(pa.float32(), 12)

_SIDE = 3
_SHAPE = (_SIDE, _SIDE + 1)
_SQUARE_TOLERANCE = 1e-3


def transforms(a: Matrix, origin: Vector) -> pa.Array:
    """Return `[Aᵀ | Aᵀ·origin]` of each row, as the canonical column."""
    import numpy as np

    rows = len(origin[0])
    r = [[a[k][i] for k in range(_SIDE)] for i in range(_SIDE)]
    flat = np.empty((rows, _SIDE * (_SIDE + 1)), np.float32)
    entries = (x for row in r for x in (*row, _dot(row, origin)))
    for column, entry in enumerate(entries):
        flat[:, column] = entry
    values = pa.array(flat.ravel())
    return pa.FixedSizeListArray.from_arrays(values, _SIDE * (_SIDE + 1))


def matrices(column: Transforms) -> np.ndarray:
    """Return each transform as a 3x4 array of doubles, NaN where null.

    `column` is the canonical column as Arrow, pandas or polars hold it.
    """
    import numpy as np

    array = _combined(column)
    width = _SIDE * (_SIDE + 1)
    flat = array.values.slice(array.offset * width, len(array) * width)
    values = np.asarray(
        flat.to_numpy(zero_copy_only=False), dtype=np.float64
    ).reshape(-1, *_SHAPE)
    if array.null_count:
        values[~np.asarray(array.is_valid())] = np.nan
    return values


def euler(column: Transforms) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return Relion's rot, tilt and psi of each transform, in degrees."""
    a, _ = relion(column)
    return euler_angles(a)


def relion(column: Transforms) -> tuple[Matrix, Vector]:
    """Return Relion's `A` and origin, in Ångström, of each transform."""
    m = matrices(column)
    a = tuple(tuple(m[:, j, i] for j in range(_SIDE)) for i in range(_SIDE))
    shift = tuple(m[:, i, _SIDE] for i in range(_SIDE))
    return a, tuple(_dot(row, shift) for row in a)


def euler_matrix(
    rot: np.ndarray, tilt: np.ndarray, psi: np.ndarray
) -> Matrix:
    """Return Relion's `A` of ZYZ angles in degrees, as Relion builds it."""
    ca, sa = _cos_sin(rot)
    cb, sb = _cos_sin(tilt)
    cg, sg = _cos_sin(psi)
    cc, cs, sc, ss = cb * ca, cb * sa, sb * ca, sb * sa
    return (
        (cg * cc - sg * sa, cg * cs + sg * ca, -cg * sb),
        (-sg * cc - cg * sa, -sg * cs + cg * ca, sg * sb),
        (sc, ss, cb),
    )


def euler_angles(a: Matrix) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return Relion's rot, tilt and psi of each `A`, in degrees.

    As Relion's `Euler_matrix2angles`: where the tilt is 0 or 180 the
    in-plane rotation is psi's and rot is 0.
    """
    import numpy as np

    sin_tilt = np.sqrt(a[0][2] * a[0][2] + a[1][2] * a[1][2])
    general = sin_tilt > 16 * np.finfo(np.float64).eps
    upright = a[2][2] > 0
    psi = np.where(
        general,
        each("atan2", a[1][2], -a[0][2]),
        np.where(
            upright,
            each("atan2", -a[1][0], a[0][0]),
            each("atan2", a[1][0], -a[0][0]),
        ),
    )
    rot = np.where(general, each("atan2", a[2][1], a[2][0]), 0.0)
    tilt = np.where(
        general,
        each("atan2", sin_tilt, a[2][2]),
        np.where(upright, 0.0, np.pi),
    )
    return np.degrees(rot), np.degrees(tilt), np.degrees(psi)


def check_rotation(a: Matrix) -> None:
    """Raise unless every `A` is a rotation, with no scale and no mirror."""
    import numpy as np

    off = np.zeros(len(a[0][0]), dtype=bool)
    for i in range(_SIDE):
        for j in range(i, _SIDE):
            gram = _dot(a[i], a[j]) - (1.0 if i == j else 0.0)
            off |= np.abs(gram) > _SQUARE_TOLERANCE
    off |= _determinant(a) < 0
    if off.any():
        raise ValueError(
            f"The transform of row {int(np.argmax(off))} scales, shears or "
            "mirrors, which Euler angles cannot say"
        )


def each(function: str, *arrays: np.ndarray) -> np.ndarray:
    """Apply an Arrow compute function, which takes one row at a time."""
    import numpy as np

    columns = [pa.array(array, pa.float64()) for array in arrays]
    result = pc.call_function(function, columns)
    return np.asarray(result.to_numpy(zero_copy_only=False), np.float64)


def _cos_sin(degrees: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    import numpy as np

    radians = np.radians(degrees)
    return each("cos", radians), each("sin", radians)


def _dot(xs: Iterable[np.ndarray], ys: Vector) -> np.ndarray:
    pairs = iter(zip(xs, ys, strict=True))
    x, y = next(pairs)
    total = x * y
    for x, y in pairs:
        total = total + x * y
    return total


def _determinant(a: Matrix) -> np.ndarray:
    return (
        a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
        - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
        + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0])
    )


def _combined(column: Transforms) -> pa.FixedSizeListArray:
    if not isinstance(column, (pa.Array, pa.ChunkedArray)):
        column = pa.array(column, TRANSFORM)
    if isinstance(column, pa.ChunkedArray):
        column = column.combine_chunks()
    return cast("pa.FixedSizeListArray", column.cast(TRANSFORM))
