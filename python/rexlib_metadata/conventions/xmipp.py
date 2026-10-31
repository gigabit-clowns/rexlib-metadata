# SPDX-License-Identifier: LGPL-2.1-or-later

"""What Xmipp's column names mean in canonical terms."""

from __future__ import annotations

from rexlib_metadata.convention import ConventionBundle
from rexlib_metadata.conventions import relion

HEADER = "# XMIPP_STAR_1 *"


class ImageReference(relion.ImageReference):
    """Splits Xmipp's `index@path`, which counts from one as Relion does."""

    source_columns = ("_image",)


class EulerAngles(relion.EulerAngles):
    """Xmipp's three ZYZ angles, the same as Relion's, in degrees."""

    source_columns = ("_angleRot", "_angleTilt", "_anglePsi")


class WriteImageReference(relion.WriteImageReference):
    """Joins a path and a zero-based index into Xmipp's `index@path`."""

    target_columns = ("_image",)


class WriteEulerAngles(relion.WriteEulerAngles):
    """Xmipp's three ZYZ angles, the same as Relion's, in degrees."""

    target_columns = ("_angleRot", "_angleTilt", "_anglePsi")


def xmipp_bundle() -> ConventionBundle:
    """Return the conventions that read and write an Xmipp file."""
    return ConventionBundle(
        "xmipp",
        read={"particles": [ImageReference(), EulerAngles()]},
        write={"particles": [WriteImageReference(), WriteEulerAngles()]},
    )
