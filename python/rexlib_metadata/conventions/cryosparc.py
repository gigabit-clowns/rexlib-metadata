# SPDX-License-Identifier: LGPL-2.1-or-later

"""What cryoSPARC's field names mean in canonical terms, read only.

A pose is a rotation vector in radians, its direction the axis and its
length the angle; it becomes Relion's ZYZ angles in degrees through the
rotation matrix. A shift is in pixels of the alignment's `psize_A`, and
the image index counts from zero, as the canonical form does. A path that
starts with `>` is relative to the cryoSPARC project; the mark is dropped.
An exposure group counts from zero and an optics group from one. A
single-precision number is read as the shortest decimal that names it,
2.7 rather than 2.700000047683716.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.compute as pc

from rexlib_metadata.convention import ConventionBundle, ReadConvention

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np

    from rexlib_metadata.convention import ArrowColumn, RawSchema

_AXES = 3


class _Fields(ReadConvention):
    """Applies where every field it reads is there."""

    def matches(self, raw: RawSchema) -> bool:
        """Apply where every source field is present."""
        return raw.has(*self.source_columns)


class _Renaming(_Fields):
    """A field under its canonical name, as a double."""

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return each field under its canonical name."""
        return {
            canonical: _double(table.column(source))
            for source, canonical in zip(
                self.source_columns, self.target_columns, strict=True
            )
        }


class ImageReference(_Fields):
    """The particle's stack and its zero-based place in it."""

    source_columns = ("blob/path", "blob/idx")
    target_columns = ("image_path", "image_index")

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return the path, and the index as the canonical integer."""
        return {
            "image_path": _unmarked(table.column("blob/path")),
            "image_index": pc.cast(table.column("blob/idx"), pa.int64()),
        }


class MicrographName(_Fields):
    """The micrograph a particle was picked from."""

    source_columns = ("location/micrograph_path",)
    target_columns = ("micrograph_path",)

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return the path without cryoSPARC's project mark."""
        path = table.column("location/micrograph_path")
        return {"micrograph_path": _unmarked(path)}


class Coordinates(_Fields):
    """Where on the micrograph a particle sits, as a fraction of it."""

    source_columns = (
        "location/center_x_frac",
        "location/center_y_frac",
        "location/micrograph_shape",
    )
    target_columns = ("coord_x", "coord_y")

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return the centre in pixels; the shape is rows, then columns."""
        shape = _rows(table.column("location/micrograph_shape"), 2)
        x = _double(table.column("location/center_x_frac"))
        y = _double(table.column("location/center_y_frac"))
        return {
            "coord_x": pc.multiply(x, pa.array(shape[:, 1])),
            "coord_y": pc.multiply(y, pa.array(shape[:, 0])),
        }


class Pose(_Fields):
    """A 3D alignment's rotation vector, as Relion's three angles."""

    source_columns = ("alignments3D/pose",)
    target_columns = ("angle_rot", "angle_tilt", "angle_psi")

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return the rotation as ZYZ angles in degrees."""
        vectors = _rows(table.column("alignments3D/pose"), _AXES)
        rot, tilt, psi = _angles(_matrices(vectors))
        return {
            "angle_rot": pa.array(rot),
            "angle_tilt": pa.array(tilt),
            "angle_psi": pa.array(psi),
        }


class Shift(_Fields):
    """A 3D alignment's shift, in pixels of its own size."""

    source_columns = ("alignments3D/shift", "alignments3D/psize_A")
    target_columns = ("shift_x", "shift_y")

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return the shift in Ångström."""
        shift = table.column(self.source_columns[0])
        x = _double(pc.list_element(shift, 0))
        y = _double(pc.list_element(shift, 1))
        size = _double(table.column(self.source_columns[1]))
        return {
            "shift_x": pc.multiply(x, size),
            "shift_y": pc.multiply(y, size),
        }


class ParticleOpticsGroup(_Fields):
    """The exposure group a particle belongs to."""

    source_columns = ("ctf/exp_group_id",)
    target_columns = ("optics_group",)

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return the group counted from one."""
        group = pc.cast(table.column("ctf/exp_group_id"), pa.int32())
        return {"optics_group": pc.add(group, pa.scalar(1, pa.int32()))}


class OpticsGroup(ParticleOpticsGroup):
    """The exposure group a row of the optics table describes."""


class Voltage(_Renaming):
    """The accelerating voltage, in kV."""

    source_columns = ("ctf/accel_kv",)
    target_columns = ("voltage",)


class SphericalAberration(_Renaming):
    """The spherical aberration, in mm."""

    source_columns = ("ctf/cs_mm",)
    target_columns = ("spherical_aberration",)


class AmplitudeContrast(_Renaming):
    """The fraction of contrast that is amplitude contrast."""

    source_columns = ("ctf/amp_contrast",)
    target_columns = ("amplitude_contrast",)


class PixelSize(_Renaming):
    """The pixel size of the particle images, in Ångström."""

    source_columns = ("blob/psize_A",)
    target_columns = ("pixel_size",)


class ImageSize(_Fields):
    """The box edge in pixels, and how many edges the shape has."""

    source_columns = ("blob/shape",)
    target_columns = ("image_size", "image_dimensionality")

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return the first edge of each image's shape, and its length."""
        shape = table.column("blob/shape")
        edges = pc.list_value_length(shape)
        return {
            "image_size": pc.cast(pc.list_element(shape, 0), pa.int64()),
            "image_dimensionality": pc.cast(edges, pa.int32()),
        }


def _double(column: ArrowColumn) -> ArrowColumn:
    if pa.types.is_float32(column.type):
        return pc.cast(pc.cast(column, pa.string()), pa.float64())
    return pc.cast(column, pa.float64())


def _unmarked(path: ArrowColumn) -> ArrowColumn:
    return pc.replace_substring_regex(path, pattern="^>", replacement="")


def _rows(column: ArrowColumn, width: int) -> np.ndarray:
    import numpy as np

    flat = pc.list_flatten(column).to_numpy(zero_copy_only=False)
    return np.asarray(flat, dtype=np.float64).reshape(-1, width)


def _matrices(vectors: np.ndarray) -> dict[str, np.ndarray]:
    """Return the entries of each vector's rotation, by Rodrigues' formula.

    Only the entries `_angles` reads, keyed by row and column. Every step
    is one element at a time, so a row's angles do not depend on how many
    rows are converted with it.
    """
    import numpy as np

    x, y, z = (np.ascontiguousarray(vectors[:, i]) for i in range(_AXES))
    angle = np.sqrt(x * x + y * y + z * z)
    length = np.where(angle > 0, angle, 1.0)
    x, y, z = x / length, y / length, z / length
    sin = _each(math.sin, angle)
    turn = 1 - _each(math.cos, angle)
    return {
        "00": 1 - turn * (y * y + z * z),
        "02": sin * y + turn * (x * z),
        "10": sin * z + turn * (x * y),
        "12": turn * (y * z) - sin * x,
        "20": turn * (x * z) - sin * y,
        "21": sin * x + turn * (y * z),
        "22": 1 - turn * (x * x + y * y),
    }


def _each(
    function: Callable[..., float], *arrays: np.ndarray
) -> np.ndarray:
    import numpy as np

    each = np.frompyfunc(function, len(arrays), 1)
    return np.asarray(each(*arrays), dtype=np.float64)


def _angles(
    a: dict[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return Relion's rot, tilt and psi of each rotation, in degrees.

    As Relion's `Euler_matrix2angles`: where the tilt is 0 or 180 the
    in-plane rotation is psi's and rot is 0.
    """
    import numpy as np

    sin_tilt = _each(math.hypot, a["02"], a["12"])
    general = sin_tilt > 16 * np.finfo(np.float64).eps
    upright = a["22"] > 0
    psi = np.where(
        general,
        _each(math.atan2, a["12"], -a["02"]),
        np.where(
            upright,
            _each(math.atan2, -a["10"], a["00"]),
            _each(math.atan2, a["10"], -a["00"]),
        ),
    )
    rot = np.where(general, _each(math.atan2, a["21"], a["20"]), 0.0)
    tilt = np.where(
        general,
        _each(math.atan2, sin_tilt, a["22"]),
        np.where(upright, 0.0, np.pi),
    )
    return np.degrees(rot), np.degrees(tilt), np.degrees(psi)


def cryosparc_bundle() -> ConventionBundle:
    """Return the conventions that read a cryoSPARC `.cs` file."""
    return ConventionBundle(
        "cryosparc",
        read={
            "particles": [
                ImageReference(),
                MicrographName(),
                Coordinates(),
                Pose(),
                Shift(),
                ParticleOpticsGroup(),
            ],
            "optics": [
                OpticsGroup(),
                Voltage(),
                SphericalAberration(),
                AmplitudeContrast(),
                PixelSize(),
                ImageSize(),
            ],
        },
    )
