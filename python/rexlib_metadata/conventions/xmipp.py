# SPDX-License-Identifier: LGPL-2.1-or-later

"""What Xmipp's column names mean in canonical terms.

Xmipp's angles are Relion's. Its shifts are in pixels and an XMD file
names no pixel size, so they are neither read nor written: a transform
read from one has no shift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rexlib_metadata.convention import ConventionBundle
from rexlib_metadata.conventions import relion

if TYPE_CHECKING:
    import numpy as np
    import pyarrow as pa

HEADER = "# XMIPP_STAR_1 *"


class ImageReference(relion.ImageReference):
    """Splits Xmipp's `index@path`, which counts from one as Relion does."""

    source_columns = ("_image",)


class Pose(relion.Pose):
    """Xmipp's ZYZ angles, as a transform with no shift."""

    angles = ("_angleRot", "_angleTilt", "_anglePsi")
    origin = ()
    source_columns = angles

    def offsets(self, table: pa.Table) -> tuple[np.ndarray, ...]:
        """Return no shift."""
        import numpy as np

        return tuple(np.zeros(table.num_rows) for _ in relion.Pose.origin)


class WriteImageReference(relion.WriteImageReference):
    """Joins a path and a zero-based index into Xmipp's `index@path`."""

    target_columns = ("_image",)


class WritePose(relion.WritePose):
    """A transform's rotation as Xmipp's ZYZ angles; its shift is not held."""

    angles = Pose.angles
    origin = ()
    target_columns = angles


def xmipp_bundle() -> ConventionBundle:
    """Return the conventions that read and write an Xmipp file."""
    return ConventionBundle(
        "xmipp",
        read={"particles": [ImageReference(), Pose()]},
        write={"particles": [WriteImageReference(), WritePose()]},
    )
