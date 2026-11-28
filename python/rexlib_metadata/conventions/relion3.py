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
from rexlib_metadata.conventions import relion
from rexlib_metadata.conventions.relion import parsed
from rexlib_metadata.conventions.settings import SettingGroup

if TYPE_CHECKING:
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


class OpticsGroup(_Relion30, SettingGroup):
	"""The group of each row's microscope and detector setting."""

	source_columns = _SETTING

	def spelled(self, column: ArrowColumn) -> ArrowColumn:
		"""Return a value as the number it reads as, so 300 is 300.0."""
		return pc.cast(parsed(column, pa.float64()), pa.string())


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
		"""Apply where an origin is in pixels."""
		return not raw.has("_rlnOpticsGroup") and relion.any_of(
			raw, self.origin
		)

	def offsets(self, table: pa.Table) -> tuple[np.ndarray, ...]:
		"""Return each row's origin in Ångström.

		A non-zero origin needs a finite pixel size, and a block with no
		detector has none.
		"""
		if not set(_DETECTOR).issubset(table.column_names):
			raise ValueError(
				"an origin in pixels needs _rlnDetectorPixelSize and "
				"_rlnMagnification to be in Ångström, and the block has "
				"neither"
			)
		size = _pixel_size(table).to_numpy(zero_copy_only=False)
		return tuple(
			_scaled(relion.numbers(table, n), size, n) for n in self.origin
		)


def _scaled(pixels: np.ndarray, size: np.ndarray, column: str) -> np.ndarray:
	import numpy as np

	with np.errstate(invalid="ignore"):
		angstrom = np.where(pixels == 0, 0.0, pixels * size)
	if not np.isfinite(angstrom).all():
		row = int(np.argmax(~np.isfinite(angstrom)))
		raise ValueError(
			f"{column} is {pixels[row]} px in row {row}, whose detector "
			"gives no finite pixel size to put it in Ångström"
		)
	return angstrom


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
