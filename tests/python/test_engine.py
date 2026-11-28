# SPDX-License-Identifier: LGPL-2.1-or-later

import pyarrow as pa
import pytest

from rexlib_metadata.convention import (
    ConventionBundle,
    RawTable,
    ReadConvention,
)
from rexlib_metadata.engine import read_canonical
from rexlib_metadata.schema import ColumnDescriptor, Schema, TableSchema

PARTICLES = TableSchema(
    "particles",
    ColumnDescriptor("image_path", pa.string(), required=True),
    ColumnDescriptor("angle_rot", pa.float64(), unit="degrees"),
    ColumnDescriptor("angle_tilt", pa.float64(), unit="degrees"),
    ColumnDescriptor("class_id", pa.int32(), default=1),
    ColumnDescriptor("phase_shift", pa.float64(), unit="degrees"),
)

RAW = RawTable.of(
    "particles",
    pa.table(
        {
            "_rlnImageName": ["a.mrcs", "b.mrcs", "c.mrcs"],
            "_rlnAngleRot": ["10.5", "30.2", "50.7"],
        }
    ),
)


class _Images(ReadConvention):
    source_columns = ("_rlnImageName",)
    target_columns = ("image_path",)

    def matches(self, raw):
        return raw.has(*self.source_columns)

    def load(self, table):
        return {"image_path": table.column("_rlnImageName").combine_chunks()}


class _Rot(ReadConvention):
    source_columns = ("_rlnAngleRot",)
    target_columns = ("angle_rot",)
    value = 10.5

    def matches(self, raw):
        return raw.has(*self.source_columns)

    def load(self, table):
        return {
            "angle_rot": pa.array(
                [self.value] * table.num_rows, type=pa.float64()
            )
        }


class _OtherRot(_Rot):
    value = 99.9


class _Exploding(ReadConvention):
    target_columns = ("angle_rot",)

    def matches(self, raw):
        return True

    def load(self, table):
        raise AssertionError("load was called")


class _Undeclared(ReadConvention):
    target_columns = ("angle_phi",)

    def matches(self, raw):
        return True

    def load(self, table):
        return {"angle_phi": pa.array([1.0] * table.num_rows)}


class _WrongType(ReadConvention):
    target_columns = ("angle_tilt",)

    def matches(self, raw):
        return True

    def load(self, table):
        return {"angle_tilt": table.column("_rlnAngleRot").combine_chunks()}


class _Shorter(ReadConvention):
    target_columns = ("angle_tilt",)

    def matches(self, raw):
        return True

    def load(self, table):
        return {"angle_tilt": pa.array([1.0], type=pa.float64())}


def _a_bundle(name, *conventions):
    return ConventionBundle(name, {"particles": list(conventions)})


def _read(*bundles, raw_tables=(RAW,), schema=PARTICLES):
    return read_canonical(raw_tables, bundles, Schema(schema), schema.name)


def test_a_bundle_produces_the_canonical_columns():
    table = _read(_a_bundle("relion4", _Images(), _Rot()))
    assert table.column_names == ["image_path", "angle_rot", "class_id"]
    assert table.column("angle_rot").to_pylist() == [10.5, 10.5, 10.5]


def test_the_first_bundle_to_produce_a_column_owns_it():
    table = _read(
        _a_bundle("mylab", _Images(), _Rot()),
        _a_bundle("relion4", _OtherRot()),
    )
    assert table.column("angle_rot").to_pylist() == [10.5, 10.5, 10.5]


def test_a_convention_whose_columns_are_covered_is_not_called():
    _read(
        _a_bundle("mylab", _Images(), _Rot()),
        _a_bundle("relion4", _Exploding()),
    )


def test_a_convention_that_does_not_match_is_not_called():
    class Never(_Exploding):
        def matches(self, raw):
            return False

    _read(_a_bundle("relion4", _Images(), Never()))


def test_a_column_the_table_does_not_declare_is_an_error():
    bundle = _a_bundle("relion4", _Images(), _Undeclared())

    with pytest.raises(ValueError, match="angle_phi"):
        _read(bundle)


def test_a_column_of_the_wrong_type_is_an_error():
    bundle = _a_bundle("relion4", _Images(), _WrongType())

    with pytest.raises(TypeError, match="angle_tilt"):
        _read(bundle)


def test_a_missing_required_column_is_an_error():
    bundle = _a_bundle("relion4", _Rot())

    with pytest.raises(ValueError, match="image_path"):
        _read(bundle)


def test_columns_of_different_lengths_are_an_error():
    bundle = _a_bundle("relion4", _Images(), _Shorter())

    with pytest.raises(ValueError, match="different lengths"):
        _read(bundle)


def test_a_default_fills_a_column_nobody_produced():
    table = _read(_a_bundle("relion4", _Images()))
    assert table.column("class_id").to_pylist() == [1, 1, 1]


def test_an_optional_column_with_no_default_is_left_out():
    table = _read(_a_bundle("relion4", _Images()))
    assert "phase_shift" not in table.column_names


def test_the_columns_come_in_the_order_the_schema_declares():
    class Tilt(_Rot):
        target_columns = ("angle_tilt",)

        def load(self, table):
            return {
                "angle_tilt": pa.array(
                    [0.0] * table.num_rows, type=pa.float64()
                )
            }

    table = _read(_a_bundle("relion4", Tilt(), _Rot(), _Images()))
    assert table.column_names == [
        "image_path",
        "angle_rot",
        "angle_tilt",
        "class_id",
    ]


class _Sneaky(ReadConvention):
    target_columns = ("image_path",)

    def matches(self, raw):
        return True

    def load(self, table):
        return {
            "image_path": table.column("_rlnImageName").combine_chunks(),
            "angle_rot": pa.array([7.0] * table.num_rows, type=pa.float64()),
        }


class _LosingWrongType(ReadConvention):
    target_columns = ("angle_rot",)

    def matches(self, raw):
        return True

    def load(self, table):
        return {"angle_rot": table.column("_rlnAngleRot").combine_chunks()}


class _ChunkedRot(ReadConvention):
    target_columns = ("angle_rot",)

    def matches(self, raw):
        return True

    def load(self, table):
        chunked = pa.chunked_array(
            [pa.array([1.0, 2.0], type=pa.float64()),
             pa.array([3.0], type=pa.float64())]
        )
        return {"angle_rot": chunked}


def test_a_column_the_convention_does_not_declare_is_an_error():
    bundle = _a_bundle("relion4", _Sneaky())

    with pytest.raises(ValueError, match="does not declare"):
        _read(bundle)


def test_a_convention_that_lost_cannot_break_the_read():
    table = _read(
        _a_bundle("mylab", _Images(), _Rot()),
        _a_bundle("relion4", _LosingWrongType()),
    )
    assert table.column("angle_rot").to_pylist() == [10.5, 10.5, 10.5]


def test_a_chunked_column_is_taken_as_it_comes():
    table = _read(_a_bundle("relion4", _Images(), _ChunkedRot()))
    assert table.column("angle_rot").to_pylist() == [1.0, 2.0, 3.0]


def test_one_canonical_table_is_filled_from_one_raw_table():
    class Voltage(ReadConvention):
        target_columns = ("angle_tilt",)

        def matches(self, raw):
            return raw.has("_rlnVoltage")

        def load(self, table):
            return {"angle_tilt": pa.array([300.0] * 3, type=pa.float64())}

    optics = RawTable.of("optics", pa.table({"_rlnVoltage": ["300.0"]}))
    table = _read(
        _a_bundle("relion4", _Images(), Voltage()),
        raw_tables=(optics, RAW),
    )
    assert table.column("image_path").to_pylist() == [
        "a.mrcs",
        "b.mrcs",
        "c.mrcs",
    ]
    assert "angle_tilt" not in table.column_names


def test_the_raw_table_that_fills_it_is_the_first_that_can():
    other = RawTable.of(
        "more_particles", pa.table({"_rlnImageName": ["z.mrcs"]})
    )
    table = _read(_a_bundle("relion4", _Images()), raw_tables=(other, RAW))

    assert table.column("image_path").to_pylist() == ["z.mrcs"]
