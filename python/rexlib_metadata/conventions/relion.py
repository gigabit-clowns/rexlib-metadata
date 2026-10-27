# SPDX-License-Identifier: LGPL-2.1-or-later

"""What Relion's column names mean in canonical terms."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.compute as pc

from rexlib_metadata.convention import (
    ArrowColumn,
    ConventionBundle,
    ReadConvention,
)

if TYPE_CHECKING:
    from rexlib_metadata.convention import RawSchema

_IMAGE_REFERENCE = r"^(?:(?P<index>[0-9]+)@)?(?P<path>.*)$"


class _Renaming(ReadConvention):
    """A convention that only renames, column for column, with a cast."""

    dtype: pa.DataType = pa.float64()

    def matches(self, raw: RawSchema) -> bool:
        """Apply where every column this convention reads is present."""
        return raw.has(*self.source_columns)

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return each source column under its canonical name, cast."""
        return {
            canonical: pc.cast(table.column(source), self.dtype)
            for source, canonical in zip(
                self.source_columns, self.target_columns, strict=True
            )
        }


class ImageReference(_Renaming):
    """Splits Relion's `index@path` into a path and a zero-based index."""

    source_columns = ("_rlnImageName",)
    target_columns = ("image_path", "image_index")

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Split the reference, counting from zero where Relion counts one."""
        parts = pc.extract_regex(
            table.column("_rlnImageName"), _IMAGE_REFERENCE
        )
        written = pc.struct_field(parts, "index")
        one_based = pc.cast(
            pc.if_else(
                pc.equal(written, pa.scalar("")), pa.scalar("1"), written
            ),
            pa.int64(),
        )
        return {
            "image_path": pc.struct_field(parts, "path"),
            "image_index": pc.subtract(one_based, pa.scalar(1, pa.int64())),
        }


class MicrographName(_Renaming):
    """The micrograph a particle was taken from."""

    source_columns = ("_rlnMicrographName",)
    target_columns = ("micrograph_path",)
    dtype = pa.string()


class Coordinates(_Renaming):
    """Where on the micrograph a particle sits, in pixels."""

    source_columns = ("_rlnCoordinateX", "_rlnCoordinateY")
    target_columns = ("coord_x", "coord_y")


class CoordinateZ(_Renaming):
    """The third coordinate, which only a subtomogram has."""

    source_columns = ("_rlnCoordinateZ",)
    target_columns = ("coord_z",)


class EulerAngles(_Renaming):
    """Relion's three ZYZ angles, already in degrees."""

    source_columns = ("_rlnAngleRot", "_rlnAngleTilt", "_rlnAnglePsi")
    target_columns = ("angle_rot", "angle_tilt", "angle_psi")


class CtfMaxResolution(_Renaming):
    """How far the CTF fit was trusted, in Ångström."""

    source_columns = ("_rlnCtfMaxResolution",)
    target_columns = ("ctf_max_resolution",)


class ParticleOpticsGroup(_Renaming):
    """Which optics group a particle belongs to."""

    source_columns = ("_rlnOpticsGroup",)
    target_columns = ("optics_group",)
    dtype = pa.int32()


class OpticsGroup(_Renaming):
    """The optics group a row of the optics table describes."""

    source_columns = ("_rlnOpticsGroup",)
    target_columns = ("optics_group",)
    dtype = pa.int32()


class Microscope(_Renaming):
    """What the microscope was set to."""

    source_columns = (
        "_rlnVoltage",
        "_rlnSphericalAberration",
        "_rlnAmplitudeContrast",
    )
    target_columns = ("voltage", "spherical_aberration", "amplitude_contrast")


class PixelSize(_Renaming):
    """The pixel size of the particle images, in Ångström."""

    source_columns = ("_rlnImagePixelSize",)
    target_columns = ("pixel_size",)


class ImageSize(_Renaming):
    """The box edge in pixels, and whether it is a square or a cube."""

    source_columns = ("_rlnImageSize", "_rlnImageDimensionality")
    target_columns = ("image_size", "image_dimensionality")

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return the box edge as an integer, and the dimensionality."""
        return {
            "image_size": pc.cast(table.column("_rlnImageSize"), pa.int64()),
            "image_dimensionality": pc.cast(
                table.column("_rlnImageDimensionality"), pa.int32()
            ),
        }


def particles_bundle() -> ConventionBundle:
    """Return the conventions that read a Relion particle table."""
    return ConventionBundle(
        "relion4_particles",
        [
            ImageReference(),
            MicrographName(),
            Coordinates(),
            CoordinateZ(),
            EulerAngles(),
            CtfMaxResolution(),
            ParticleOpticsGroup(),
        ],
    )


def optics_bundle() -> ConventionBundle:
    """Return the conventions that read a Relion optics table."""
    return ConventionBundle(
        "relion4_optics",
        [OpticsGroup(), Microscope(), PixelSize(), ImageSize()],
    )
