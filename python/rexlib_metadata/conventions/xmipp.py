# SPDX-License-Identifier: LGPL-2.1-or-later

"""What Xmipp's column names mean in canonical terms."""

from __future__ import annotations

from rexlib_metadata.convention import ConventionBundle
from rexlib_metadata.conventions import relion

HEADER = "# XMIPP_STAR_1 *"


class ImageReference(relion.ImageReference):
    """Splits Xmipp's `index@path`, which counts from one as Relion does."""

    source_columns = ("_image",)


class AngleRot(relion.AngleRot):
    """The first of Xmipp's ZYZ angles, the same as Relion's."""

    source_columns = ("_angleRot",)


class AngleTilt(relion.AngleTilt):
    """The second of Xmipp's ZYZ angles, the same as Relion's."""

    source_columns = ("_angleTilt",)


class AnglePsi(relion.AnglePsi):
    """Xmipp's in-plane angle, the same as Relion's."""

    source_columns = ("_anglePsi",)


class WriteImageReference(relion.WriteImageReference):
    """Joins a path and a zero-based index into Xmipp's `index@path`."""

    target_columns = ("_image",)


class WriteAngleRot(relion.WriteAngleRot):
    """The first of Xmipp's ZYZ angles, the same as Relion's."""

    target_columns = ("_angleRot",)


class WriteAngleTilt(relion.WriteAngleTilt):
    """The second of Xmipp's ZYZ angles, the same as Relion's."""

    target_columns = ("_angleTilt",)


class WriteAnglePsi(relion.WriteAnglePsi):
    """Xmipp's in-plane angle, the same as Relion's."""

    target_columns = ("_anglePsi",)


def xmipp_bundle() -> ConventionBundle:
    """Return the conventions that read and write an Xmipp file."""
    return ConventionBundle(
        "xmipp",
        read={
            "particles": [ImageReference(), AngleRot(), AngleTilt(), AnglePsi()]
        },
        write={
            "particles": [
                WriteImageReference(),
                WriteAngleRot(),
                WriteAngleTilt(),
                WriteAnglePsi(),
            ]
        },
    )
