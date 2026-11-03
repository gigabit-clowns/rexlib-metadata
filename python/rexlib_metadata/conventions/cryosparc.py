# SPDX-License-Identifier: LGPL-2.1-or-later

"""What cryoSPARC's field names mean in canonical terms, read only.

A pose is a rotation vector in radians, its direction the axis and its
length the angle; its rotation matrix is Relion's `A`. A shift is in
pixels of the alignment's `psize_A`, and the image index counts from
zero, as the canonical form does. A path that starts with `>` is
relative to the cryoSPARC project; the mark is dropped. An exposure group
counts from zero and an optics group from one. A single-precision number
is read as the shortest decimal that names it, 2.7 rather than
2.700000047683716.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.compute as pc

from rexlib_metadata import pose
from rexlib_metadata.convention import ConventionBundle, ReadConvention

if TYPE_CHECKING:
    import numpy as np

    from rexlib_metadata.convention import ArrowColumn, RawSchema
    from rexlib_metadata.pose import Matrix

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
    """A 3D alignment's rotation vector and shift, as one transform.

    The shift is in pixels of the alignment's own size, and is zero where
    the file has none.
    """

    source_columns = (
        "alignments3D/pose",
        "alignments3D/shift",
        "alignments3D/psize_A",
    )
    target_columns = ("transform",)

    def matches(self, raw: RawSchema) -> bool:
        """Apply where the rotation vector is there."""
        return raw.has(self.source_columns[0])

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return the rotation as Relion's `A`, the shift in Ångström."""
        vectors = _rows(table.column(self.source_columns[0]), _AXES)
        a = _matrices(vectors)
        return {"transform": pose.transforms(a, _origin(table))}


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


def _origin(table: pa.Table) -> tuple[np.ndarray, ...]:
    import numpy as np

    shift, size = Pose.source_columns[1:]
    if not {shift, size}.issubset(table.column_names):
        return tuple(np.zeros(table.num_rows) for _ in range(_AXES))
    pixels = _rows(table.column(shift), 2)
    angstrom = _double(table.column(size)).to_numpy()
    x, y = (np.ascontiguousarray(pixels[:, i]) * angstrom for i in range(2))
    return x, y, np.zeros(table.num_rows)


def _matrices(vectors: np.ndarray) -> Matrix:
    """Return each vector's rotation, by Rodrigues' formula."""
    import numpy as np

    x, y, z = (np.ascontiguousarray(vectors[:, i]) for i in range(_AXES))
    angle = np.sqrt(x * x + y * y + z * z)
    length = np.where(angle > 0, angle, 1.0)
    x, y, z = x / length, y / length, z / length
    sin = pose.each("sin", angle)
    turn = 1 - pose.each("cos", angle)
    return (
        (
            1 - turn * (y * y + z * z),
            turn * (x * y) - sin * z,
            sin * y + turn * (x * z),
        ),
        (
            sin * z + turn * (x * y),
            1 - turn * (x * x + z * z),
            turn * (y * z) - sin * x,
        ),
        (
            turn * (x * z) - sin * y,
            sin * x + turn * (y * z),
            1 - turn * (x * x + y * y),
        ),
    )


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
