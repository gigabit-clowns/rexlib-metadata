# SPDX-License-Identifier: LGPL-2.1-or-later

import pyarrow as pa
import pytest

from rexlib_metadata.schema import (
    ColumnDescriptor,
    Schema,
    SchemaTrait,
    TableSchema,
)

ROT = ColumnDescriptor("angle_rot", pa.float64(), unit="degrees")
TILT = ColumnDescriptor("angle_tilt", pa.float64(), unit="degrees")
PSI = ColumnDescriptor("angle_psi", pa.float64(), unit="degrees")
IMAGE = ColumnDescriptor("image_path", pa.string(), required=True)

EULER = SchemaTrait("euler_angles", (ROT, TILT, PSI))
POSITION = SchemaTrait(
    "cartesian_position",
    (
        ColumnDescriptor("coord_x", pa.float64(), unit="px"),
        ColumnDescriptor("coord_y", pa.float64(), unit="px"),
    ),
)


def test_a_column_is_optional_by_default():
    assert not ROT.required


def test_required_and_defaulted_at_once_is_an_error():
    dtype = pa.int32()

    with pytest.raises(ValueError, match="required and has a default"):
        ColumnDescriptor("class_id", dtype, required=True, default=1)


def test_a_trait_flattens_into_the_table():
    table = TableSchema("particles", EULER, POSITION)
    assert [c.name for c in table] == [
        "angle_rot",
        "angle_tilt",
        "angle_psi",
        "coord_x",
        "coord_y",
    ]


def test_a_loose_column_composes_beside_a_trait():
    table = TableSchema("particles", IMAGE, EULER)
    assert next(c.name for c in table) == "image_path"
    assert len(table) == 4


def test_the_same_column_twice_collapses():
    other = SchemaTrait("pose", (ROT,))
    table = TableSchema("particles", EULER, other)
    assert len(table) == 3


@pytest.mark.parametrize(
    "clashing",
    [
        pytest.param(
            ColumnDescriptor("angle_rot", pa.float32(), unit="degrees"),
            id="dtype",
        ),
        pytest.param(
            ColumnDescriptor("angle_rot", pa.float64(), unit="radians"),
            id="unit",
        ),
        pytest.param(
            ColumnDescriptor("angle_rot", pa.float64(), unit="degrees",
                             required=True),
            id="required",
        ),
        pytest.param(
            ColumnDescriptor("angle_rot", pa.float64(), unit="degrees",
                             default=0.0),
            id="default",
        ),
    ],
)
def test_two_declarations_that_disagree_are_an_error(clashing):
    other = SchemaTrait("other", (clashing,))

    with pytest.raises(ValueError, match="angle_rot"):
        TableSchema("particles", EULER, other)


def test_required_columns_are_the_required_ones():
    table = TableSchema("particles", IMAGE, EULER)
    assert [c.name for c in table.required_columns] == ["image_path"]


def test_a_column_is_reachable_by_name():
    table = TableSchema("particles", EULER)
    assert table.column("angle_tilt") is TILT
    assert "angle_tilt" in table


def test_an_unknown_column_raises():
    table = TableSchema("particles", EULER)
    with pytest.raises(KeyError, match="no column 'angle_phi'"):
        table.column("angle_phi")


def test_a_schema_holds_its_tables_by_name():
    particles = TableSchema("particles", EULER)
    optics = TableSchema("optics", ColumnDescriptor("voltage", pa.float64()))
    schema = Schema(particles, optics)
    assert len(schema) == 2
    assert schema["optics"] is optics
    assert "particles" in schema
    assert [t.name for t in schema] == ["particles", "optics"]


def test_two_tables_of_one_name_are_an_error():
    particles = TableSchema("particles", EULER)
    again = TableSchema("particles")

    with pytest.raises(ValueError, match="declared twice"):
        Schema(particles, again)


def test_an_unknown_table_raises():
    schema = Schema(TableSchema("particles", EULER))
    with pytest.raises(KeyError, match="No table 'optics'"):
        schema["optics"]
