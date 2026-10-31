# SPDX-License-Identifier: LGPL-2.1-or-later

"""What a STAR file costs to read and write, one operation per benchmark."""

import pytest

import rexlib_metadata as rxm


@pytest.mark.benchmark
def test_read_the_raw_tables(particles_star):
    rxm.read(str(particles_star)).raw.tables()


@pytest.mark.benchmark
def test_read_the_canonical_particles(particles_star):
    rxm.read(str(particles_star))["particles"].to_pandas()


@pytest.mark.benchmark
def test_read_two_canonical_columns(particles_star):
    rxm.read(str(particles_star), columns=["angle_rot", "angle_tilt"])[
        "particles"
    ].to_pandas()


@pytest.mark.benchmark
def test_read_the_particles_in_chunks(particles_star):
    for chunk in rxm.read(str(particles_star))["particles"].chunks(10_000):
        chunk.to_arrow()


@pytest.mark.benchmark
def test_read_the_particles_joined_to_their_optics(particles_star):
    rxm.read(str(particles_star)).joined("particles").to_pandas()


@pytest.mark.benchmark
def test_write_the_whole_file_back(particles_star, tmp_path):
    rxm.read(str(particles_star)).write(str(tmp_path / "out.star"))
