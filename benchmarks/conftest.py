# SPDX-License-Identifier: LGPL-2.1-or-later

import os
from pathlib import Path

import pytest

from benchmarks.generate import write

ROWS = int(os.environ.get("REXLIB_BENCH_ROWS", "100000"))


@pytest.fixture(scope="session")
def particles_star(tmp_path_factory) -> Path:
    """A Relion-like particles file of REXLIB_BENCH_ROWS rows, or 100k."""
    return write(tmp_path_factory.mktemp("bench") / "particles.star", ROWS)
