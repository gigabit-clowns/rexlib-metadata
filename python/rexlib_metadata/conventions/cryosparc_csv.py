# SPDX-License-Identifier: LGPL-2.1-or-later

"""What the columns of cryoSPARC's v0.65 `.csv` mean, read only.

A pose is `alignments.model.r`, a rotation vector in radians as in a
`.cs`, and `alignments.model.t`, a shift in pixels of `ctf_params.psize`.
The image index counts from zero. The file names no exposure group, so
each distinct microscope setting is a group, numbered from one as first
held, and the optics table is read from the particles' rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.compute as pc

from rexlib_metadata import pose
from rexlib_metadata.convention import ConventionBundle, ReadConvention
from rexlib_metadata.conventions.cryosparc import degrees, rotations
from rexlib_metadata.conventions.settings import SettingGroup

if TYPE_CHECKING:
	import numpy as np

	from rexlib_metadata.convention import ArrowColumn, RawSchema

_ROTATION = tuple(f"alignments.model.r.{axis}" for axis in range(3))
_SHIFT = ("alignments.model.t.0", "alignments.model.t.1")
_PIXEL_SIZE = "ctf_params.psize"
_SETTING = ("ctf_params.akv", "ctf_params.cs", "ctf_params.wgh", _PIXEL_SIZE)


class _Fields(ReadConvention):
	"""Applies where every column it reads is there."""

	def matches(self, raw: RawSchema) -> bool:
		"""Apply where every source column is present."""
		return raw.has(*self.source_columns)


class _Renaming(_Fields):
	"""A column under its canonical name, as a double."""

	def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
		"""Return each column under its canonical name."""
		return {
			canonical: pc.cast(table.column(source), pa.float64())
			for source, canonical in zip(
				self.source_columns, self.target_columns, strict=True
			)
		}


class ImageReference(_Fields):
	"""The particle's stack and its zero-based place in it."""

	source_columns = ("data_input_relpath", "data_input_idx")
	target_columns = ("image_path", "image_index")

	def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
		"""Return the path, and the index as the canonical integer."""
		index = table.column("data_input_idx")
		return {
			"image_path": table.column("data_input_relpath"),
			"image_index": pc.cast(index, pa.int64()),
		}


class Pose(_Fields):
	"""The rotation vector and the shift, as one transform.

	The shift is zero where the file has none.
	"""

	source_columns = (*_ROTATION, *_SHIFT, _PIXEL_SIZE)
	target_columns = ("transform",)

	def matches(self, raw: RawSchema) -> bool:
		"""Apply where the rotation vector is there."""
		return raw.has(*_ROTATION)

	def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
		"""Return the rotation as Relion's `A`, the shift in Ångström."""
		import numpy as np

		vectors = np.column_stack([_numbers(table, c) for c in _ROTATION])
		return {
			"transform": pose.transforms(rotations(vectors), _origin(table))
		}


class Defocus(_Renaming):
	"""The CTF's two defocus values, in Ångström, and their angle."""

	source_columns = (
		"ctf_params.df1",
		"ctf_params.df2",
		"ctf_params.angast_deg",
	)
	target_columns = ("defocus_u", "defocus_v", "defocus_angle")


class PhaseShift(_Fields):
	"""The phase plate's shift, in degrees."""

	source_columns = ("ctf_params.phase_shift",)
	target_columns = ("phase_shift",)

	def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
		"""Return the shift in degrees, where the file holds radians."""
		radians = pc.cast(table.column("ctf_params.phase_shift"), pa.float64())
		return {"phase_shift": degrees(radians)}


class OpticsGroup(_Fields, SettingGroup):
	"""The group of each row's microscope setting."""

	source_columns = _SETTING


class Voltage(_Renaming):
	"""The accelerating voltage, in kV."""

	source_columns = ("ctf_params.akv",)
	target_columns = ("voltage",)


class SphericalAberration(_Renaming):
	"""The spherical aberration, in mm."""

	source_columns = ("ctf_params.cs",)
	target_columns = ("spherical_aberration",)


class AmplitudeContrast(_Renaming):
	"""The fraction of contrast that is amplitude contrast."""

	source_columns = ("ctf_params.wgh",)
	target_columns = ("amplitude_contrast",)


class PixelSize(_Renaming):
	"""The pixel size of the particle images, in Ångström."""

	source_columns = (_PIXEL_SIZE,)
	target_columns = ("pixel_size",)


def _numbers(table: pa.Table, column: str) -> np.ndarray:
	import numpy as np

	values = pc.cast(table.column(column), pa.float64()).to_numpy()
	return np.asarray(values, dtype=np.float64)


def _origin(table: pa.Table) -> tuple[np.ndarray, ...]:
	import numpy as np

	zero = np.zeros(table.num_rows)
	if not set(_SHIFT) & set(table.column_names):
		return zero, zero, zero
	if _PIXEL_SIZE not in table.column_names:
		raise ValueError(
			f"{', '.join(_SHIFT)} are in pixels, and the file has no "
			f"{_PIXEL_SIZE} to put them in Ångström"
		)
	size = _numbers(table, _PIXEL_SIZE)
	x, y = (
		_numbers(table, c) * size if c in table.column_names else zero
		for c in _SHIFT
	)
	return x, y, zero


def cryosparc_csv_bundle() -> ConventionBundle:
	"""Return the conventions that read a cryoSPARC v0.65 `.csv` file."""
	return ConventionBundle(
		"cryosparc_csv",
		read={
			"particles": [
				ImageReference(),
				Pose(),
				Defocus(),
				PhaseShift(),
				OpticsGroup(),
			],
			"optics": [
				OpticsGroup(),
				Voltage(),
				SphericalAberration(),
				AmplitudeContrast(),
				PixelSize(),
			],
		},
	)
