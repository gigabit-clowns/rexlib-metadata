# SPDX-License-Identifier: LGPL-2.1-or-later

"""What FREALIGN's `.par` columns mean in canonical terms, read only.

`C` numbers the particle from one in a stack the file does not name, so a
read names it: `frealign_bundle(stack=...)`. `PHI`, `THETA` and `PSI` are
Relion's rot, tilt and psi; `SHX` and `SHY` are the opposite of Relion's
origin, in Ångström.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.compute as pc

from rexlib_metadata.convention import ConventionBundle, ReadConvention
from rexlib_metadata.conventions import relion

if TYPE_CHECKING:
	import numpy as np

	from rexlib_metadata.convention import ArrowColumn, RawSchema


class ImageReference(ReadConvention):
	"""The particle's place in the stack the read names, from zero."""

	source_columns = ("C",)
	target_columns = ("image_path", "image_index")

	def __init__(self, stack: str | None) -> None:
		"""Place every particle in `stack`, or refuse to read with none."""
		self._stack = stack

	def matches(self, raw: RawSchema) -> bool:
		"""Apply where the particle's number is there."""
		return raw.has("C")

	def load(self, table: pa.Table) -> dict[str, ArrowColumn]:
		"""Return the stack, and `C` counted from zero."""
		if self._stack is None:
			raise ValueError(
				"A .par names no image stack: read it with "
				"bundle=frealign_bundle(stack=...)"
			)
		number = relion.parsed(table.column("C"), pa.int64())
		return {
			"image_path": pa.array([self._stack] * table.num_rows, pa.string()),
			"image_index": pc.subtract(number, pa.scalar(1, pa.int64())),
		}


class Pose(relion.Pose):
	"""FREALIGN's angles and shift, as one transform."""

	angles = ("PHI", "THETA", "PSI")
	origin = ("SHX", "SHY")
	source_columns = (*angles, *origin)

	def matches(self, raw: RawSchema) -> bool:
		"""Apply where any of the angles or shifts is there."""
		return relion.any_of(raw, self.source_columns)

	def offsets(self, table: pa.Table) -> tuple[np.ndarray, ...]:
		"""Return Relion's origin: the opposite of the shift, z zero."""
		import numpy as np

		x, y = (-relion.numbers(table, name) for name in self.origin)
		return x, y, np.zeros(table.num_rows)


class Defocus(relion.Defocus):
	"""The CTF's two defocus values, in Ångström, and their angle."""

	source_columns = ("DF1", "DF2", "ANGAST")


def frealign_bundle(stack: str | None = None) -> ConventionBundle:
	"""Return the conventions that read a FREALIGN `.par`, in `stack`."""
	return ConventionBundle(
		"frealign",
		read={"particles": [ImageReference(stack), Pose(), Defocus()]},
	)
