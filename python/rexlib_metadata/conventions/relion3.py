# SPDX-License-Identifier: LGPL-2.1-or-later

"""What Relion 3.0's own names mean, read only.

Relion 3.0 has no optics table: each particle carries its microscope and
its detector. A group is each distinct setting, numbered from one in the
order the file first holds it, and the optics table is read from the
same rows, one per group.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pyarrow as pa
import pyarrow.compute as pc

from rexlib_metadata.convention import ConventionBundle, ReadConvention
from rexlib_metadata.conventions import relion
from rexlib_metadata.conventions.relion import parsed

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    import numpy as np

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
        return self.in_context([table]).load(table)

    def in_context(self, chunks: Iterable[pa.Table]) -> ReadConvention:
        """Return the groups numbered as the whole table first holds them."""
        held: pa.Array = pa.array([], pa.string())
        for chunk in chunks:
            found = cast("pa.Array", pc.unique(_setting(chunk)))
            fresh = found.filter(pc.invert(pc.is_in(found, value_set=held)))
            held = pa.concat_arrays([held, fresh])
        return _Numbered(held)


class _Numbered(OpticsGroup):
    """Groups numbered by their place among the settings of a whole table."""

    def __init__(self, held: pa.Array) -> None:
        self._held = held

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return each setting's place among those held, from one."""
        place = pc.index_in(_setting(table), value_set=self._held)
        group = pc.add(place, pa.scalar(1, pa.int32()))
        return {"optics_group": pc.cast(group, pa.int32())}


class PixelSize(_Relion30):
    """The pixel size, from the detector's in micrometres and the zoom."""

    source_columns = _DETECTOR
    target_columns = ("pixel_size",)

    def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
        """Return the detector pixel over the magnification, in Ångström."""
        return {"pixel_size": _pixel_size(table)}


class Pose(relion.Pose):
    """Relion's angles with Relion 3.0's origin, in pixels."""

    origin = relion.PIXEL_ORIGIN
    source_columns = (*relion.Pose.angles, *origin, *_DETECTOR)

    def matches(self, raw: RawSchema) -> bool:
        """Apply where an origin in pixels has a detector to scale it."""
        return (
            not raw.has("_rlnOpticsGroup")
            and relion.any_of(raw, self.origin)
            and raw.has(*_DETECTOR)
        )

    def offsets(self, table: pa.Table) -> tuple[np.ndarray, ...]:
        """Return each row's origin in Ångström."""
        size = _pixel_size(table).to_numpy()
        return tuple(relion.numbers(table, n) * size for n in self.origin)


def _setting(table: pa.Table) -> ArrowColumn:
    join: Callable[..., ArrowColumn] = pc.binary_join_element_wise
    return join(*(table.column(c) for c in _SETTING), pa.scalar("\x1f"))


def _pixel_size(table: pa.Table) -> ArrowColumn:
    detector = parsed(table.column("_rlnDetectorPixelSize"), pa.float64())
    magnification = parsed(table.column("_rlnMagnification"), pa.float64())
    return pc.divide(pc.multiply(detector, 1e4), magnification)


def relion3_bundle() -> ConventionBundle:
    """Return the conventions that read a Relion 3.0 file.

    Read only: Relion 3.0 is written by nothing current, and a Relion 3.0
    file read through these writes back as Relion 4, optics table and all.
    """
    return ConventionBundle(
        "relion3",
        read={
            "particles": [OpticsGroup(), Pose()],
            "optics": [OpticsGroup(), PixelSize()],
            "micrographs": [OpticsGroup()],
        },
    )
