# SPDX-License-Identifier: LGPL-2.1-or-later

"""The EMPIAR files under tests/files are what their README says they are."""

from pathlib import Path

import numpy as np

FILES = Path(__file__).parent.parent / "files"


def test_the_par_file_is_a_header_and_ten_fixed_width_rows():
    lines = (FILES / "par" / "Frealign9Parameter_0_r1.par").read_text()
    header, *rows = lines.splitlines()

    assert header.split()[:4] == ["C", "PSI", "THETA", "PHI"]
    assert len(rows) == 10
    assert {len(row) for row in rows} == {136}
    assert {len(row.split()) for row in rows} == {16}


def test_the_csv_file_is_one_block_declaring_its_types():
    lines = (FILES / "csv" / "final.csv").read_text().split("\n")

    assert lines[:4] == ["", "", "_table,images", "_header"]
    assert lines[5] == "_dtypes"
    width = len(lines[4].split(","))
    rows = lines[7:-3]
    assert len(lines[6].split(",")) == width
    assert len(rows) == 10
    assert {len(row.split(",")) for row in rows} == {width}
    assert lines[-3:] == ["", "", ""]


def test_the_cs_file_is_ten_rows_of_eighty_five_fields():
    array = np.load(FILES / "cs" / "J114_particles_exported.cs")

    assert array.shape == (10,)
    assert len(array.dtype.names) == 85
    assert array.dtype["alignments3D/pose"].shape == (3,)
    assert array["blob/path"][0].startswith(b">")
