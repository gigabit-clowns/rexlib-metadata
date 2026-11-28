# SPDX-License-Identifier: LGPL-2.1-or-later

import pytest

import rexlib_metadata as rxm
from rexlib_metadata import pose
from rexlib_metadata.conventions.frealign import frealign_bundle

from .support import PAR, assert_same

_STACK = "particles.mrcs"


@pytest.fixture
def _raw():
	return rxm.read(str(PAR)).raw.to_pandas()


def _particles():
	bundle = frealign_bundle(stack=_STACK)
	return rxm.read(str(PAR), bundle=bundle)["particles"]


def test_a_par_read_without_a_stack_asks_for_one():
	view = rxm.read(str(PAR))["particles"]

	with pytest.raises(ValueError, match=r"frealign_bundle\(stack=\.\.\.\)"):
		view.to_pandas()


def test_each_particle_is_its_place_in_the_stack_counted_from_zero(_raw):
	df = _particles().to_pandas()

	assert df["image_path"].tolist() == [_STACK] * len(_raw)
	assert df["image_index"].tolist() == (_raw["C"].astype(int) - 1).tolist()


def test_the_angles_are_relions_rot_tilt_and_psi(_raw):
	df = _particles().to_pandas()

	rot, tilt, psi = pose.euler(df["transform"])

	for got, name in zip(
		(rot, tilt, psi), ("PHI", "THETA", "PSI"), strict=True
	):
		turn = (got - _raw[name].astype(float) + 180.0) % 360.0 - 180.0
		assert turn.tolist() == pytest.approx([0.0] * len(df), abs=1e-3)


def test_the_shift_is_the_opposite_of_relions_origin(_raw):
	df = _particles().to_pandas()

	_, origin = pose.relion(df["transform"])

	for axis, name in enumerate(("SHX", "SHY")):
		expected = -_raw[name].astype(float)
		assert origin[axis].tolist() == pytest.approx(
			expected.tolist(), abs=1e-4
		)
	assert origin[2].tolist() == pytest.approx([0.0] * len(df), abs=1e-4)


def test_the_defocus_is_df1_df2_and_angast(_raw):
	df = _particles().to_pandas()

	for canonical, name in (
		("defocus_u", "DF1"),
		("defocus_v", "DF2"),
		("defocus_angle", "ANGAST"),
	):
		assert df[canonical].tolist() == _raw[name].astype(float).tolist()


def test_a_par_file_converts_to_relion(tmp_path):
	out = tmp_path / "out.star"
	source = rxm.read(str(PAR), bundle=frealign_bundle(stack=_STACK))

	source.write(str(out))

	again = rxm.read(str(out))["particles"].to_pandas()
	assert_same(again, source["particles"].to_pandas())
