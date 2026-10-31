# SPDX-License-Identifier: LGPL-2.1-or-later

"""A Relion-like particles file of any size, the same bytes every time."""

from __future__ import annotations

import random
from pathlib import Path

_OPTICS = """
# version 30001

data_optics

loop_
_rlnOpticsGroupName #1
_rlnOpticsGroup #2
_rlnVoltage #3
_rlnSphericalAberration #4
_rlnAmplitudeContrast #5
_rlnImagePixelSize #6
_rlnImageSize #7
_rlnImageDimensionality #8
opticsGroup1 1 300.0 2.7 0.1 1.06 256 2
opticsGroup2 2 300.0 2.7 0.1 1.06 256 2

"""

_COLUMNS = (
    "_rlnCoordinateX",
    "_rlnCoordinateY",
    "_rlnAngleRot",
    "_rlnAngleTilt",
    "_rlnAnglePsi",
    "_rlnOriginXAngst",
    "_rlnOriginYAngst",
    "_rlnDefocusU",
    "_rlnDefocusV",
    "_rlnDefocusAngle",
    "_rlnCtfBfactor",
    "_rlnCtfMaxResolution",
    "_rlnCtfFigureOfMerit",
    "_rlnNormCorrection",
    "_rlnLogLikeliContribution",
    "_rlnMaxValueProbDistribution",
    "_rlnClassNumber",
    "_rlnRandomSubset",
    "_rlnOpticsGroup",
    "_rlnMicrographName",
    "_rlnImageName",
)


def write(path: Path, rows: int) -> Path:
    """Write `rows` particles to `path`, seeded so the file never changes."""
    draw = random.Random(rows)
    header = "".join(f"{name} #{i}\n" for i, name in enumerate(_COLUMNS, 1))
    with path.open("w", encoding="ascii", newline="\n") as out:
        out.write(_OPTICS)
        out.write("# version 30001\n\ndata_particles\n\nloop_\n" + header)
        for row in range(rows):
            out.write(_row(draw, row))
    return path


def _row(draw: random.Random, row: int) -> str:
    numbers = [f"{draw.uniform(0, 4096):.6f}" for _ in range(2)]
    numbers += [f"{draw.uniform(-180, 180):.6f}" for _ in range(3)]
    numbers += [f"{draw.uniform(-20, 20):.6f}" for _ in range(2)]
    numbers += [f"{draw.uniform(5000, 30000):.6f}" for _ in range(2)]
    numbers += [f"{draw.uniform(0, 180):.6f}", "0.000000", "4.200000"]
    numbers += [f"{draw.random():.6f}" for _ in range(4)]
    micrograph = row // 200
    numbers += [
        str(draw.randint(1, 10)),
        str(row % 2 + 1),
        str(micrograph % 2 + 1),
        f"MotionCorr/job002/Movies/mic_{micrograph:05d}.mrc",
        f"{row % 200 + 1:06d}@Extract/job007/Movies/mic_{micrograph:05d}.mrcs",
    ]
    return " ".join(numbers) + "\n"
