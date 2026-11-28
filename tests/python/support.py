# SPDX-License-Identifier: LGPL-2.1-or-later

"""The fixtures' paths and the helpers more than one test file uses."""

from pathlib import Path

import numpy as np
import pandas as pd

from rexlib_metadata import pose
from rexlib_metadata.convention import ConventionBundle
from rexlib_metadata.conventions.relion import Pose, relion4_bundle
from rexlib_metadata.formats.star import StarReader
from rexlib_metadata.registry import MetadataRegistry

FILES = Path(__file__).parent.parent / "files"
STAR = FILES / "star"
XMD = FILES / "xmd"
CS = FILES / "cs" / "J114_particles_exported.cs"
SUBTOMO = STAR / "relion3.1_subtomo.star"
POLISHED = STAR / "relion3.0_polished.star"
MICROGRAPHS = STAR / "relion3.0_micrographs.star"


def assert_same(left, right):
    """Compare canonical frames, a transform to its single precision."""
    exact = [c for c in left.columns if c != "transform"]
    pd.testing.assert_frame_equal(left[exact], right[exact])
    if "transform" in left.columns:
        np.testing.assert_allclose(
            pose.matrices(left["transform"]),
            pose.matrices(right["transform"]),
            atol=1e-5,
        )


def relion_matrix(rot, tilt, psi):
    """Return Relion's rotation for ZYZ angles in degrees."""
    a, b, g = np.radians([rot, tilt, psi])
    ca, sa, cb, sb, cg, sg = (
        np.cos(a), np.sin(a), np.cos(b), np.sin(b), np.cos(g), np.sin(g)
    )
    return np.array(
        [
            [cg * cb * ca - sg * sa, cg * cb * sa + sg * ca, -cg * sb],
            [-sg * cb * ca - cg * sa, -sg * cb * sa + cg * ca, sg * sb],
            [sb * ca, sb * sa, cb],
        ]
    )


def registry_of(reader):
    """Return a registry reading `.star` through `reader`, as Relion 4."""
    registry = MetadataRegistry()
    registry.register_reader([".star"], reader)
    registry.register_bundle([".star"], relion4_bundle())
    return registry


class CountingStar(StarReader):
    """A STAR reader that counts the times it reads a file whole."""

    def __init__(self):
        self.whole = 0

    def read_tables(self, path):
        self.whole += 1
        return super().read_tables(path)

    def read_tables_keeping(self, path, columns):
        self.whole += 1
        return super().read_tables_keeping(path, columns)


class MovedPose(Pose):
    """Relion's pose, its origin moved one Ångström along x."""

    def offsets(self, table):
        x, y, z = super().offsets(table)
        return x + 1.0, y, z


def mylab():
    """Return a bundle of one's own, reading particles through `MovedPose`."""
    return ConventionBundle("mylab", read={"particles": [MovedPose()]})
