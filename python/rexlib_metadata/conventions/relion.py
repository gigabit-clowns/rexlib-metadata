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
    WriteConvention,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from rexlib_metadata.convention import RawSchema

_INDEX_WIDTH = 6


class _Renaming(ReadConvention):
    """A convention that only renames, column for column, with a cast."""

    dtype: pa.DataType = pa.float64()

    def matches(self, raw: RawSchema) -> bool:
        """Apply where every column this convention reads is present."""
        return raw.has(*self.source_columns)

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return each source column under its canonical name, cast."""
        return {
            canonical: parsed(table.column(source), self.dtype)
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
        written, path = split_reference(table.column(self.source_columns[0]))
        one_based = pc.cast(written, pa.int64())
        return {
            "image_path": path,
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


class AngleRot(_Renaming):
    """The first of Relion's ZYZ angles, in degrees."""

    source_columns = ("_rlnAngleRot",)
    target_columns = ("angle_rot",)


class AngleTilt(_Renaming):
    """The second of Relion's ZYZ angles, in degrees."""

    source_columns = ("_rlnAngleTilt",)
    target_columns = ("angle_tilt",)


class AnglePsi(_Renaming):
    """The in-plane angle, which a 2D classification carries on its own."""

    source_columns = ("_rlnAnglePsi",)
    target_columns = ("angle_psi",)


class Origin(_Renaming):
    """How far a particle sits from the centre of its box, in Ångström."""

    source_columns = ("_rlnOriginXAngst", "_rlnOriginYAngst")
    target_columns = ("shift_x", "shift_y")


class OriginZ(_Renaming):
    """The third offset, which only a subtomogram has."""

    source_columns = ("_rlnOriginZAngst",)
    target_columns = ("shift_z",)


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
            "image_size": parsed(table.column("_rlnImageSize"), pa.int64()),
            "image_dimensionality": parsed(
                table.column("_rlnImageDimensionality"), pa.int32()
            ),
        }


class _Spelling(WriteConvention):
    """A convention that only renames, column for column, as text.

    The cast is Arrow's: the shortest text that reads back as the same
    number. Relion's own files disagree about how many decimals to write,
    so there is no habit of the format to imitate.
    """

    def store(
        self, canonical: dict[str, ArrowColumn]
    ) -> dict[str, ArrowColumn]:
        """Return each canonical column under its file name, as text."""
        return {
            file_column: pc.cast(canonical[source], pa.string())
            for source, file_column in zip(
                self.source_columns, self.target_columns, strict=True
            )
        }


class WriteImageReference(_Spelling):
    """Joins a path and a zero-based index into Relion's `index@path`."""

    source_columns = ("image_path", "image_index")
    target_columns = ("_rlnImageName",)

    def store(
        self, canonical: dict[str, ArrowColumn]
    ) -> dict[str, ArrowColumn]:
        """Count from one where the canonical form counts from zero."""
        one_based = pc.add(canonical["image_index"], pa.scalar(1, pa.int64()))
        return {
            self.target_columns[0]: _joined(
                _padded(one_based), canonical["image_path"], "@"
            )
        }


class WriteMicrographName(_Spelling):
    """The micrograph a particle was taken from."""

    source_columns = ("micrograph_path",)
    target_columns = ("_rlnMicrographName",)


class WriteCoordinates(_Spelling):
    """Where on the micrograph a particle sits, in pixels."""

    source_columns = ("coord_x", "coord_y")
    target_columns = ("_rlnCoordinateX", "_rlnCoordinateY")


class WriteCoordinateZ(_Spelling):
    """The third coordinate, which only a subtomogram has."""

    source_columns = ("coord_z",)
    target_columns = ("_rlnCoordinateZ",)


class WriteAngleRot(_Spelling):
    """The first of Relion's ZYZ angles, in degrees."""

    source_columns = ("angle_rot",)
    target_columns = ("_rlnAngleRot",)


class WriteAngleTilt(_Spelling):
    """The second of Relion's ZYZ angles, in degrees."""

    source_columns = ("angle_tilt",)
    target_columns = ("_rlnAngleTilt",)


class WriteAnglePsi(_Spelling):
    """The in-plane angle, which a 2D classification carries on its own."""

    source_columns = ("angle_psi",)
    target_columns = ("_rlnAnglePsi",)


class WriteOrigin(_Spelling):
    """How far a particle sits from the centre of its box, in Ångström."""

    source_columns = ("shift_x", "shift_y")
    target_columns = ("_rlnOriginXAngst", "_rlnOriginYAngst")


class WriteOriginZ(_Spelling):
    """The third offset, which only a subtomogram has."""

    source_columns = ("shift_z",)
    target_columns = ("_rlnOriginZAngst",)


class WriteCtfMaxResolution(_Spelling):
    """How far the CTF fit was trusted, in Ångström."""

    source_columns = ("ctf_max_resolution",)
    target_columns = ("_rlnCtfMaxResolution",)


class WriteParticleOpticsGroup(_Spelling):
    """Which optics group a particle belongs to."""

    source_columns = ("optics_group",)
    target_columns = ("_rlnOpticsGroup",)


class WriteOpticsGroup(_Spelling):
    """The optics group a row of the optics table describes."""

    source_columns = ("optics_group",)
    target_columns = ("_rlnOpticsGroup",)


class WriteMicroscope(_Spelling):
    """What the microscope was set to."""

    source_columns = (
        "voltage",
        "spherical_aberration",
        "amplitude_contrast",
    )
    target_columns = (
        "_rlnVoltage",
        "_rlnSphericalAberration",
        "_rlnAmplitudeContrast",
    )


class WritePixelSize(_Spelling):
    """The pixel size of the particle images, in Ångström."""

    source_columns = ("pixel_size",)
    target_columns = ("_rlnImagePixelSize",)


class WriteImageSize(_Spelling):
    """The box edge in pixels, and whether it is a square or a cube."""

    source_columns = ("image_size", "image_dimensionality")
    target_columns = ("_rlnImageSize", "_rlnImageDimensionality")


def parsed(column: ArrowColumn, dtype: pa.DataType) -> ArrowColumn:
    """Cast text to `dtype`, an empty value being a null.

    A text format has no spelling for a null and writes it empty, so an
    empty number is the null it was, not a value that fails to parse.
    """
    if pa.types.is_string(dtype):
        return pc.cast(column, dtype)
    return pc.cast(_empty_as_null(column), dtype)


def _empty_as_null(column: ArrowColumn) -> ArrowColumn:
    written = pc.not_equal(column, pa.scalar(""))
    return pc.if_else(written, column, pa.nulls(len(column), pa.string()))


def split_reference(
    reference: pa.ChunkedArray,
) -> tuple[ArrowColumn, ArrowColumn]:
    """Split `index@path` into the one-based index as written, and the path.

    The index is the ASCII digits before the first `@`, and only those: a
    reference whose text before its first `@` is anything else, or that
    has no `@`, is a path and nothing more, and its index is the first,
    `"1"`. A null reference stays null in both.
    """
    pieces = pc.split_pattern(reference.combine_chunks(), "@", max_splits=1)
    head = pc.list_element(pieces, 0)
    rest = pc.binary_join(pc.list_slice(pieces, 1), "@")
    indexed = pc.and_(
        pc.and_(
            pc.equal(pc.list_value_length(pieces), pa.scalar(2)),
            pc.not_equal(head, pa.scalar("")),
        ),
        pc.ascii_is_decimal(head),
    )
    index = pc.if_else(indexed, head, pa.scalar("1"))
    path = pc.if_else(indexed, rest, reference)
    return index, path


def _joined(
    head: ArrowColumn, tail: ArrowColumn, separator: str
) -> ArrowColumn:
    join: Callable[..., ArrowColumn] = pc.binary_join_element_wise
    return join(head, tail, pa.scalar(separator))


def _padded(index: ArrowColumn) -> ArrowColumn:
    return pc.utf8_lpad(pc.cast(index, pa.string()), _INDEX_WIDTH, padding="0")


def relion4_bundle() -> ConventionBundle:
    """Return the conventions that read and write a Relion 4 file."""
    return ConventionBundle(
        "relion4",
        read={
            "particles": [
                ImageReference(),
                MicrographName(),
                Coordinates(),
                CoordinateZ(),
                AngleRot(),
                AngleTilt(),
                AnglePsi(),
                Origin(),
                OriginZ(),
                CtfMaxResolution(),
                ParticleOpticsGroup(),
            ],
            "optics": [
                OpticsGroup(),
                Microscope(),
                PixelSize(),
                ImageSize(),
            ],
        },
        write={
            "particles": [
                WriteImageReference(),
                WriteMicrographName(),
                WriteCoordinates(),
                WriteCoordinateZ(),
                WriteAngleRot(),
                WriteAngleTilt(),
                WriteAnglePsi(),
                WriteOrigin(),
                WriteOriginZ(),
                WriteCtfMaxResolution(),
                WriteParticleOpticsGroup(),
            ],
            "optics": [
                WriteOpticsGroup(),
                WriteMicroscope(),
                WritePixelSize(),
                WriteImageSize(),
            ],
        },
    )
