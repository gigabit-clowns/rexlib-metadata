# SPDX-License-Identifier: LGPL-2.1-or-later

import numpy as np
import pandas as pd
import pytest

import rexlib_metadata as rxm
from rexlib_metadata import pose

from .support import CSV, assert_same, rodrigues


@pytest.fixture
def _raw():
	return rxm.read(str(CSV)).raw.to_pandas()


def test_a_csv_file_is_read_without_being_told_what_it_is():
	assert rxm.read(str(CSV)).names == ("particles", "optics")


def test_the_particles_come_back_canonical(_raw):
	df = rxm.read(str(CSV))["particles"].to_pandas()

	assert df["image_path"].tolist() == _raw["data_input_relpath"].tolist()
	assert df["image_index"].tolist() == _raw["data_input_idx"].tolist()
	assert df["defocus_u"].tolist() == _raw["ctf_params.df1"].tolist()
	assert df["defocus_v"].tolist() == _raw["ctf_params.df2"].tolist()
	assert df["defocus_angle"].tolist() == (
		_raw["ctf_params.angast_deg"].tolist()
	)
	shift = np.degrees(_raw["ctf_params.phase_shift"])
	assert df["phase_shift"].tolist() == pytest.approx(shift.tolist())


def test_a_pose_becomes_the_transpose_of_its_rotation(_raw):
	df = rxm.read(str(CSV))["particles"].to_pandas()

	rotations = pose.matrices(df["transform"])[:, :, :3]

	vectors = _raw[[f"alignments.model.r.{i}" for i in range(3)]].to_numpy()
	for row, vector in enumerate(vectors):
		np.testing.assert_allclose(
			rotations[row], rodrigues(vector).T, atol=1e-6
		)


def test_a_shift_comes_back_in_angstrom(_raw):
	df = rxm.read(str(CSV))["particles"].to_pandas()

	_, origin = pose.relion(df["transform"])

	size = _raw["ctf_params.psize"]
	for axis in range(2):
		expected = _raw[f"alignments.model.t.{axis}"] * size
		assert origin[axis].tolist() == pytest.approx(
			expected.tolist(), abs=1e-4
		)


def test_the_optics_are_one_row_per_setting(_raw):
	optics = rxm.read(str(CSV))["optics"].to_pandas()

	assert optics["optics_group"].tolist() == [1]
	assert optics["voltage"].tolist() == [_raw["ctf_params.akv"][0]]
	assert optics["spherical_aberration"].tolist() == [_raw["ctf_params.cs"][0]]
	assert optics["amplitude_contrast"].tolist() == [_raw["ctf_params.wgh"][0]]
	assert optics["pixel_size"].tolist() == [_raw["ctf_params.psize"][0]]


def test_two_settings_are_two_groups_numbered_as_first_held(tmp_path):
	lines = CSV.read_text().split("\n")
	names = lines[4].split(",")
	voltage = names.index("ctf_params.akv")
	rows = [line.split(",") for line in lines[7:] if line]
	for row in rows[1::2]:
		row[voltage] = "200.0"
	path = tmp_path / "two.csv"
	path.write_text("\n".join([*lines[:7], *(",".join(r) for r in rows)]))

	result = rxm.read(str(path))

	groups = result["particles"].to_pandas()["optics_group"].tolist()
	assert groups == [1, 2] * (len(rows) // 2)
	optics = result["optics"].to_pandas()
	assert optics["voltage"].tolist() == [300.0, 200.0]


def test_a_csv_file_converts_to_relion(tmp_path):
	out = tmp_path / "out.star"
	source = rxm.read(str(CSV))

	source.write(str(out))

	again = rxm.read(str(out))
	for name in ("particles", "optics"):
		assert_same(again[name].to_pandas(), source[name].to_pandas())


def test_a_csv_file_reads_in_chunks_as_it_reads_whole():
	view = rxm.read(str(CSV)).joined("particles")

	chunks = [chunk.to_pandas() for chunk in view.chunks(3)]

	assert_same(pd.concat(chunks, ignore_index=True), view.to_pandas())
