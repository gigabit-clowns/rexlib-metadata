# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import pytest

import rexlib_metadata as rxm
from rexlib_metadata.conventions.relion import relion4_bundle

FILES = Path(__file__).parent.parent / "files" / "star"
STAR = FILES / "relion3.1_subtomo.star"


@pytest.fixture(params=[".star", ".sqlite", ".h5"])
def source(request, tmp_path):
    if request.param == ".h5":
        pytest.importorskip("h5py")
    if request.param == ".star":
        return str(STAR)
    path = str(tmp_path / f"subtomo{request.param}")
    rxm.read(str(STAR)).raw.write(path)
    return path


@pytest.mark.parametrize("size", [0, -1])
def test_a_chunk_of_no_rows_is_refused(source, size):
    result = rxm.read(source, bundle=relion4_bundle())
    particles = result["particles"]

    with pytest.raises(ValueError, match="at least one row"):
        particles.chunks(size)
    with pytest.raises(ValueError, match="at least one row"):
        result.raw.chunks(size)
