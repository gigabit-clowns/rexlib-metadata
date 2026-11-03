# SPDX-License-Identifier: LGPL-2.1-or-later

"""What Relion 3.0's own names mean, read only.

Relion 3.0 has no optics table: each particle carries its microscope and
its detector. A group is each distinct setting, numbered from one in the
order the file first holds it, and the optics table is read from the
same rows, one per group.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.compute as pc

from rexlib_metadata.convention import ConventionBundle, ReadConvention
from rexlib_metadata.conventions.relion import parsed

if TYPE_CHECKING:
    from collections.abc import Callable

    from rexlib_metadata.convention import ArrowColumn, RawSchema

_SETTING = (
    "_rlnVoltage",
    "_rlnSphericalAberration",
    "_rlnAmplitudeContrast",
    "_rlnMagnification",
    "_rlnDetectorPixelSize",
)
_DETECTOR = ("_rlnMagnification", "_rlnDetectorPixelSize")


class _Relion30(ReadConvention):
    """Applies where the file has no optics group of its own."""

    def matches(self, raw: RawSchema) -> bool:
        """Apply where every source column is there and no optics group."""
        return raw.has(*self.source_columns) and not raw.has("_rlnOpticsGroup")


class OpticsGroup(_Relion30):
    """The group of each row's microscope and detector setting."""

    source_columns = _SETTING
    target_columns = ("optics_group",)

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return each distinct setting numbered from one, as first held."""
        return {"optics_group": _groups(table, _SETTING)}


class PixelSize(_Relion30):
    """The pixel size, from the detector's in micrometres and the zoom."""

    source_columns = _DETECTOR
    target_columns = ("pixel_size",)

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return the detector pixel over the magnification, in Ångström."""
        return {"pixel_size": _pixel_size(table)}


class Origin(_Relion30):
    """The offset from the box centre, written in pixels."""

    source_columns = ("_rlnOriginX", "_rlnOriginY", *_DETECTOR)
    target_columns = ("shift_x", "shift_y")

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return each offset in Ångström."""
        size = _pixel_size(table)
        return {
            "shift_x": _in_angstrom(table, "_rlnOriginX", size),
            "shift_y": _in_angstrom(table, "_rlnOriginY", size),
        }


class OriginZ(_Relion30):
    """The third offset, which only a subtomogram has, in pixels."""

    source_columns = ("_rlnOriginZ", *_DETECTOR)
    target_columns = ("shift_z",)

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return the offset in Ångström."""
        size = _pixel_size(table)
        return {"shift_z": _in_angstrom(table, "_rlnOriginZ", size)}


def _groups(table: pa.Table, columns: tuple[str, ...]) -> ArrowColumn:
    join: Callable[..., ArrowColumn] = pc.binary_join_element_wise
    setting = join(*(table.column(c) for c in columns), pa.scalar("\x1f"))
    first_held = pc.unique(setting)
    group = pc.add(pc.index_in(setting, value_set=first_held), 1)
    return pc.cast(group, pa.int32())


def _pixel_size(table: pa.Table) -> ArrowColumn:
    detector = parsed(table.column("_rlnDetectorPixelSize"), pa.float64())
    magnification = parsed(table.column("_rlnMagnification"), pa.float64())
    return pc.divide(pc.multiply(detector, 1e4), magnification)


def _in_angstrom(
    table: pa.Table, column: str, size: ArrowColumn
) -> ArrowColumn:
    return pc.multiply(parsed(table.column(column), pa.float64()), size)


def relion3_bundle() -> ConventionBundle:
    """Return the conventions that read a Relion 3.0 file.

    Read only: Relion 3.0 is written by nothing current, and a Relion 3.0
    file read through these writes back as Relion 4, optics table and all.
    """
    return ConventionBundle(
        "relion3",
        read={
            "particles": [OpticsGroup(), Origin(), OriginZ()],
            "optics": [OpticsGroup(), PixelSize()],
        },
    )
