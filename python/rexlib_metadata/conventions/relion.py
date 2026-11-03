# SPDX-License-Identifier: LGPL-2.1-or-later

"""What Relion's column names mean in canonical terms."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pyarrow as pa
import pyarrow.compute as pc

from rexlib_metadata import pose
from rexlib_metadata.convention import (
    ArrowColumn,
    ConventionBundle,
    ReadConvention,
    WriteConvention,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np

    from rexlib_metadata.convention import RawSchema

_INDEX_WIDTH = 6
_POSE_ROWS = 1 << 20
PIXEL_ORIGIN = ("_rlnOriginX", "_rlnOriginY", "_rlnOriginZ")


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


class Micrograph(MicrographName):
    """A row of a micrographs table: a micrograph, and no particle in it."""

    def matches(self, raw: RawSchema) -> bool:
        """Apply to a table naming micrographs and no particle image."""
        return super().matches(raw) and not raw.has("_rlnImageName")


class Defocus(_Renaming):
    """The CTF's two defocus values, in Ångström, and their angle."""

    source_columns = ("_rlnDefocusU", "_rlnDefocusV", "_rlnDefocusAngle")
    target_columns = ("defocus_u", "defocus_v", "defocus_angle")


class Coordinates(_Renaming):
    """Where on the micrograph a particle sits, in pixels."""

    source_columns = ("_rlnCoordinateX", "_rlnCoordinateY")
    target_columns = ("coord_x", "coord_y")


class CoordinateZ(_Renaming):
    """The third coordinate, which only a subtomogram has."""

    source_columns = ("_rlnCoordinateZ",)
    target_columns = ("coord_z",)


class Pose(ReadConvention):
    """Relion's ZYZ angles and origin in Ångström, as one transform.

    Any of the six may be missing, from the file or from a row, and is
    then zero. An origin in pixels is Relion 3.0's to read.
    """

    angles: tuple[str, ...] = (
        "_rlnAngleRot",
        "_rlnAngleTilt",
        "_rlnAnglePsi",
    )
    origin: tuple[str, ...] = (
        "_rlnOriginXAngst",
        "_rlnOriginYAngst",
        "_rlnOriginZAngst",
    )
    source_columns: tuple[str, ...] = (*angles, *origin)
    target_columns = ("transform",)

    def matches(self, raw: RawSchema) -> bool:
        """Apply where any of the six is there and no origin in pixels."""
        return any_of(raw, self.source_columns) and not any_of(
            raw, PIXEL_ORIGIN
        )

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return the transform of each row's angles and origin.

        A slice at a time, so that what the conversion holds stays small.
        """
        starts = range(0, max(table.num_rows, 1), _POSE_ROWS)
        slices = (table.slice(start, _POSE_ROWS) for start in starts)
        parts = [self._transforms(part) for part in slices]
        return {"transform": pa.chunked_array(parts)}

    def _transforms(self, table: pa.Table) -> pa.Array:
        rot, tilt, psi = (numbers(table, name) for name in self.angles)
        a = pose.euler_matrix(rot, tilt, psi)
        return pose.transforms(a, self.offsets(table))

    def offsets(self, table: pa.Table) -> tuple[np.ndarray, ...]:
        """Return each row's origin in Ångström."""
        return tuple(numbers(table, name) for name in self.origin)


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


class Voltage(_Renaming):
    """The accelerating voltage, in kV."""

    source_columns = ("_rlnVoltage",)
    target_columns = ("voltage",)


class SphericalAberration(_Renaming):
    """The spherical aberration, in mm."""

    source_columns = ("_rlnSphericalAberration",)
    target_columns = ("spherical_aberration",)


class AmplitudeContrast(_Renaming):
    """The fraction of contrast that is amplitude contrast."""

    source_columns = ("_rlnAmplitudeContrast",)
    target_columns = ("amplitude_contrast",)


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


class WriteDefocus(_Spelling):
    """The CTF's two defocus values, in Ångström, and their angle."""

    source_columns = ("defocus_u", "defocus_v", "defocus_angle")
    target_columns = ("_rlnDefocusU", "_rlnDefocusV", "_rlnDefocusAngle")


class WriteCoordinates(_Spelling):
    """Where on the micrograph a particle sits, in pixels."""

    source_columns = ("coord_x", "coord_y")
    target_columns = ("_rlnCoordinateX", "_rlnCoordinateY")


class WriteCoordinateZ(_Spelling):
    """The third coordinate, which only a subtomogram has."""

    source_columns = ("coord_z",)
    target_columns = ("_rlnCoordinateZ",)


class WritePose(WriteConvention):
    """A transform as Relion's ZYZ angles and origin in Ångström.

    All six are written, at single precision, as the transform holds them.
    A transform that scales, shears or mirrors has no angles and raises.
    """

    angles = Pose.angles
    origin: tuple[str, ...] = Pose.origin
    source_columns = ("transform",)
    target_columns = (*angles, *origin)

    def store(
        self, canonical: dict[str, ArrowColumn]
    ) -> dict[str, ArrowColumn]:
        """Return the angles in degrees, then the origin in Ångström."""
        a, offsets = pose.relion(canonical["transform"])
        pose.check_rotation(a)
        angles = pose.euler_angles(a)
        written = dict(zip(self.angles, map(single, angles), strict=True))
        if self.origin:
            written.update(zip(self.origin, map(single, offsets), strict=True))
        return written


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


class WriteVoltage(_Spelling):
    """The accelerating voltage, in kV."""

    source_columns = ("voltage",)
    target_columns = ("_rlnVoltage",)


class WriteSphericalAberration(_Spelling):
    """The spherical aberration, in mm."""

    source_columns = ("spherical_aberration",)
    target_columns = ("_rlnSphericalAberration",)


class WriteAmplitudeContrast(_Spelling):
    """The fraction of contrast that is amplitude contrast."""

    source_columns = ("amplitude_contrast",)
    target_columns = ("_rlnAmplitudeContrast",)


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


def numbers(table: pa.Table, column: str) -> np.ndarray:
    """Return a text column as doubles, zero where empty or not there."""
    import numpy as np

    if column not in table.column_names:
        return np.zeros(table.num_rows)
    parsed_column = parsed(table.column(column), pa.float64())
    values = cast("pa.ChunkedArray", parsed_column).fill_null(pa.scalar(0.0))
    return np.asarray(values.to_numpy(), dtype=np.float64)


def single(values: np.ndarray) -> ArrowColumn:
    """Spell doubles as the shortest text of their single precision.

    A NaN, a null transform's, is a null.
    """
    import numpy as np

    array = pa.array(values.astype(np.float32), from_pandas=True)
    return pc.cast(array, pa.string())


def any_of(raw: RawSchema, columns: tuple[str, ...]) -> bool:
    """Say whether the table declares at least one of `columns`."""
    return any(raw.has(column) for column in columns)


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
                Pose(),
                CtfMaxResolution(),
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
            "micrographs": [
                Micrograph(),
                Defocus(),
                CtfMaxResolution(),
                ParticleOpticsGroup(),
            ],
        },
        write={
            "particles": [
                WriteImageReference(),
                WriteMicrographName(),
                WriteCoordinates(),
                WriteCoordinateZ(),
                WritePose(),
                WriteCtfMaxResolution(),
                WriteParticleOpticsGroup(),
            ],
            "optics": [
                WriteOpticsGroup(),
                WriteVoltage(),
                WriteSphericalAberration(),
                WriteAmplitudeContrast(),
                WritePixelSize(),
                WriteImageSize(),
            ],
            "micrographs": [
                WriteMicrographName(),
                WriteDefocus(),
                WriteCtfMaxResolution(),
                WriteParticleOpticsGroup(),
            ],
        },
    )
