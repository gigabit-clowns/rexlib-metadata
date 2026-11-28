# SPDX-License-Identifier: LGPL-2.1-or-later


import pandas as pd
import pyarrow as pa
import pytest

import rexlib_metadata as rxm
from rexlib_metadata.canonical import SCHEMA
from rexlib_metadata.join import joined
from rexlib_metadata.schema import (
	ColumnDescriptor,
	Relation,
	Schema,
	TableSchema,
)

from .support import STAR, assert_same

PARTICLES = pa.table({"image_index": [0, 1, 2, 3], "group": [2, 1, 2, 9]})
GROUPS = pa.table({"group": [1, 2], "voltage": [200.0, 300.0]})


def test_each_row_gains_the_columns_of_the_row_it_points_at():
	table = joined(PARTICLES, GROUPS, "group")

	assert table.column_names == ["image_index", "group", "voltage"]
	assert table.column("image_index").to_pylist() == [0, 1, 2, 3]
	assert table.column("voltage").to_pylist() == [300.0, 200.0, 300.0, None]


def test_a_key_that_repeats_says_so():
	groups = pa.table({"group": [1, 1], "voltage": [200.0, 300.0]})

	with pytest.raises(ValueError, match="'group' repeats a value"):
		joined(PARTICLES, groups, "group")


def test_a_table_without_the_key_points_at_nothing():
	table = pa.table({"image_index": [0]})

	assert joined(table, GROUPS, "group") is table


def test_a_relation_on_a_key_one_table_lacks_is_refused():
	a = TableSchema("a", ColumnDescriptor("k", pa.int32()))
	b = TableSchema("b", ColumnDescriptor("j", pa.int32()))
	relations = [Relation("a", "b", "k")]

	with pytest.raises(ValueError, match="both tables"):
		Schema(a, b, relations=relations)


def test_a_relation_between_tables_sharing_another_column_is_refused():
	shared = ColumnDescriptor("x", pa.float64())
	a = TableSchema("a", ColumnDescriptor("k", pa.int32()), shared)
	b = TableSchema("b", ColumnDescriptor("k", pa.int32()), shared)
	relations = [Relation("a", "b", "k")]

	with pytest.raises(ValueError, match="also share 'x'"):
		Schema(a, b, relations=relations)


def test_the_canonical_particles_and_micrographs_point_at_their_optics():
	assert SCHEMA.relations_of("particles") == (
		Relation("particles", "optics", "optics_group"),
	)
	assert SCHEMA.related_to("optics") == (
		*SCHEMA.relations_of("particles"),
		*SCHEMA.relations_of("micrographs"),
	)


def test_a_joined_view_carries_the_optics_on_every_particle():
	result = rxm.read(str(STAR / "relion3.1_subtomo.star"))

	flat = result.joined("particles").to_pandas()
	particles = result["particles"].to_pandas()
	optics = result["optics"].to_pandas().drop(columns="optics_group")

	assert list(flat.columns) == list(particles.columns) + list(optics.columns)
	assert len(flat) == len(particles)
	assert flat["pixel_size"].tolist() == (
		[optics["pixel_size"][0]] * len(particles)
	)


def test_particles_naming_no_optics_group_join_nothing():
	result = rxm.read(str(STAR / "rln3.1_data_style.star"))

	pd.testing.assert_frame_equal(
		result.joined("particles").to_pandas(),
		result["particles"].to_pandas(),
	)


def test_naming_columns_of_both_tables_joins_them():
	path = str(STAR / "relion3.1_subtomo.star")
	whole = rxm.read(path).joined("particles").to_pandas()

	result = rxm.read(path, columns=["coord_x", "pixel_size"])
	flat = result.joined("particles").to_pandas()

	assert list(flat.columns) == ["coord_x", "pixel_size"]
	pd.testing.assert_frame_equal(flat, whole[["coord_x", "pixel_size"]])


def test_a_joined_view_reads_in_chunks_as_it_reads_whole():
	view = rxm.read(str(STAR / "relion3.1_subtomo.star")).joined("particles")

	chunks = [chunk.to_pandas() for chunk in view.chunks(20)]

	assert [len(chunk) for chunk in chunks] == [20, 20, 17]
	pd.testing.assert_frame_equal(
		pd.concat(chunks, ignore_index=True), view.to_pandas()
	)


def test_a_format_with_no_optics_table_gets_them_in_each_row(tmp_path):
	out = tmp_path / "out.xmd"

	source = rxm.read(str(STAR / "relion3.1_subtomo.star"))
	source.write(str(out))
	again = rxm.read(str(out))

	assert again.raw.names == ("particles",)
	reference = ["image_path", "image_index"]
	assert_same(
		again["particles"].to_pandas()[reference],
		source["particles"].to_pandas()[reference],
	)


def test_a_format_with_an_optics_table_keeps_it_apart(tmp_path):
	out = tmp_path / "out.star"

	rxm.read(str(STAR / "relion3.1_subtomo.star")).write(str(out))

	assert rxm.read(str(out)).raw.names == ("optics", "particles")


def test_updates_a_folded_table_cannot_write_are_refused(tmp_path):
	view = rxm.read(str(STAR / "relion3.1_subtomo.star"))["optics"]
	optics = view.to_pandas()
	optics["voltage"] = 200.0
	out = tmp_path / "out.xmd"
	edited = view.updated(optics[["voltage"]])

	with pytest.raises(ValueError, match=r"'voltage'.*joined into 'particles'"):
		edited.write(str(out))
	assert not out.exists()


def test_rows_of_a_table_the_destination_folds_are_refused(tmp_path):
	view = rxm.read(str(STAR / "relion3.1_subtomo.star"))["optics"]
	out = str(tmp_path / "out.xmd")
	edited = view.take([0])

	with pytest.raises(ValueError, match="joins it into the rows"):
		edited.write(out)
