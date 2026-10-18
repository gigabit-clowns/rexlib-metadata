import pyarrow as pa
import pytest

from rexlib_metadata.convention import (
    ConventionBundle,
    RawTable,
    ReadConvention,
)
from rexlib_metadata.engine import read_canonical
from rexlib_metadata.schema import ColumnDescriptor, TableSchema

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


class Images(ReadConvention):
    source_columns = ("_rlnImageName",)
    target_columns = ("image_path",)

    def matches(self, raw):
        return raw.has(*self.source_columns)

    def load(self, table):
        return {"image_path": table.column("_rlnImageName").combine_chunks()}


class Rot(ReadConvention):
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


class OtherRot(Rot):
    value = 99.9


class Exploding(ReadConvention):
    target_columns = ("angle_rot",)

    def matches(self, raw):
        return True

    def load(self, table):
        raise AssertionError("load was called")


class Undeclared(ReadConvention):
    target_columns = ("angle_phi",)

    def matches(self, raw):
        return True

    def load(self, table):
        return {"angle_phi": pa.array([1.0] * table.num_rows)}


class WrongType(ReadConvention):
    target_columns = ("angle_tilt",)

    def matches(self, raw):
        return True

    def load(self, table):
        return {"angle_tilt": table.column("_rlnAngleRot").combine_chunks()}


class Shorter(ReadConvention):
    target_columns = ("angle_tilt",)

    def matches(self, raw):
        return True

    def load(self, table):
        return {"angle_tilt": pa.array([1.0], type=pa.float64())}


def read(*bundles, raw_tables=(RAW,), schema=PARTICLES):
    return read_canonical(raw_tables, bundles, schema)


def test_a_bundle_produces_the_canonical_columns():
    table = read(ConventionBundle("relion4", [Images(), Rot()]))
    assert table.column_names == ["image_path", "angle_rot", "class_id"]
    assert table.column("angle_rot").to_pylist() == [10.5, 10.5, 10.5]


def test_the_first_bundle_to_produce_a_column_owns_it():
    table = read(
        ConventionBundle("mylab", [Images(), Rot()]),
        ConventionBundle("relion4", [OtherRot()]),
    )
    assert table.column("angle_rot").to_pylist() == [10.5, 10.5, 10.5]


def test_a_convention_whose_columns_are_covered_is_not_called():
    read(
        ConventionBundle("mylab", [Images(), Rot()]),
        ConventionBundle("relion4", [Exploding()]),
    )


def test_a_convention_that_does_not_match_is_not_called():
    class Never(Exploding):
        def matches(self, raw):
            return False

    read(ConventionBundle("relion4", [Images(), Never()]))


def test_a_column_the_table_does_not_declare_is_an_error():
    with pytest.raises(ValueError, match="angle_phi"):
        read(ConventionBundle("relion4", [Images(), Undeclared()]))


def test_a_column_of_the_wrong_type_is_an_error():
    with pytest.raises(TypeError, match="angle_tilt"):
        read(ConventionBundle("relion4", [Images(), WrongType()]))


def test_a_missing_required_column_is_an_error():
    with pytest.raises(ValueError, match="image_path"):
        read(ConventionBundle("relion4", [Rot()]))


def test_columns_of_different_lengths_are_an_error():
    with pytest.raises(ValueError, match="different lengths"):
        read(ConventionBundle("relion4", [Images(), Shorter()]))


def test_a_default_fills_a_column_nobody_produced():
    table = read(ConventionBundle("relion4", [Images()]))
    assert table.column("class_id").to_pylist() == [1, 1, 1]


def test_an_optional_column_with_no_default_is_left_out():
    table = read(ConventionBundle("relion4", [Images()]))
    assert "phase_shift" not in table.column_names


def test_the_columns_come_in_the_order_the_schema_declares():
    class Tilt(Rot):
        target_columns = ("angle_tilt",)

        def load(self, table):
            return {
                "angle_tilt": pa.array(
                    [0.0] * table.num_rows, type=pa.float64()
                )
            }

    table = read(ConventionBundle("relion4", [Tilt(), Rot(), Images()]))
    assert table.column_names == [
        "image_path",
        "angle_rot",
        "angle_tilt",
        "class_id",
    ]




class Sneaky(ReadConvention):
    target_columns = ("image_path",)

    def matches(self, raw):
        return True

    def load(self, table):
        return {
            "image_path": table.column("_rlnImageName").combine_chunks(),
            "angle_rot": pa.array([7.0] * table.num_rows, type=pa.float64()),
        }


class LosingWrongType(ReadConvention):
    target_columns = ("angle_rot",)

    def matches(self, raw):
        return True

    def load(self, table):
        return {"angle_rot": table.column("_rlnAngleRot").combine_chunks()}


class ChunkedRot(ReadConvention):
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
    with pytest.raises(ValueError, match="does not declare"):
        read(ConventionBundle("relion4", [Sneaky()]))


def test_a_convention_that_lost_cannot_break_the_read():
    table = read(
        ConventionBundle("mylab", [Images(), Rot()]),
        ConventionBundle("relion4", [LosingWrongType()]),
    )
    assert table.column("angle_rot").to_pylist() == [10.5, 10.5, 10.5]


def test_a_chunked_column_is_taken_as_it_comes():
    table = read(ConventionBundle("relion4", [Images(), ChunkedRot()]))
    assert table.column("angle_rot").to_pylist() == [1.0, 2.0, 3.0]


def test_two_raw_tables_each_give_what_they_have():
    class Voltage(ReadConvention):
        target_columns = ("angle_tilt",)

        def matches(self, raw):
            return raw.has("_rlnVoltage")

        def load(self, table):
            return {"angle_tilt": pa.array([300.0] * 3, type=pa.float64())}

    optics = RawTable.of("optics", pa.table({"_rlnVoltage": ["300.0"]}))
    table = read(
        ConventionBundle("relion4", [Images(), Voltage()]),
        raw_tables=(optics, RAW),
    )
    assert table.column("image_path").to_pylist() == ["a.mrcs", "b.mrcs", "c.mrcs"]
    assert table.column("angle_tilt").to_pylist() == [300.0, 300.0, 300.0]
