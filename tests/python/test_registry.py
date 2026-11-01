# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pytest

import rexlib_metadata as rxm
from rexlib_metadata.abc import Reader
from rexlib_metadata.canonical import OPTICS, PARTICLES, SCHEMA
from rexlib_metadata.convention import (
    ConventionBundle,
    RawTable,
    ReadConvention,
)
from rexlib_metadata.registry import MetadataRegistry
from rexlib_metadata.schema import ColumnDescriptor, Schema, TableSchema

SUBTOMO = str(
    Path(__file__).parent.parent / "files" / "star" / "relion3.1_subtomo.star"
)


class _Reader(Reader):
    def read_tables(self, path):
        return [RawTable.of("a_table", pa.table({"a": [1]}))]


def test_bundles_come_back_in_priority_order():
    registry = MetadataRegistry()
    registry.register_bundle([".star"], ConventionBundle("relion4"))
    registry.register_bundle([".star"], ConventionBundle("relion3"))
    registry.register_bundle([".star"], ConventionBundle("mylab"), prepend=True)

    assert [b.name for b in registry.bundles_for("x.star")] == [
        "mylab",
        "relion4",
        "relion3",
    ]


def test_an_extension_with_no_bundle_has_none():
    assert MetadataRegistry().bundles_for("x.star") == ()


def test_a_bundle_registers_for_several_extensions():
    registry = MetadataRegistry()
    registry.register_bundle([".star", ".xmd"], ConventionBundle("relion4"))

    assert len(registry.bundles_for("x.star")) == 1
    assert len(registry.bundles_for("x.xmd")) == 1
    assert registry.bundles_for("x.cs") == ()


def test_an_extension_is_matched_whatever_its_case():
    registry = MetadataRegistry()
    registry.register_bundle([".Star"], ConventionBundle("relion4"))

    assert len(registry.bundles_for("X.STAR")) == 1


def test_an_extension_with_no_reader_raises():
    registry = MetadataRegistry()

    with pytest.raises(ValueError, match="No reader registered"):
        registry.reader_for("data.csv")


def test_the_registered_reader_is_the_one_handed_back():
    reader = _Reader()
    registry = MetadataRegistry()
    registry.register_reader([".star"], reader)

    assert registry.reader_for("x.star") is reader
    assert registry.reader_for("X.STAR") is reader


def test_reading_goes_through_the_reader_of_the_extension():
    reader = _Reader()
    registry = MetadataRegistry()
    registry.register_reader([".star"], reader)

    assert registry.read("x.star").raw._reader is reader


def test_one_extension_may_be_given_as_a_string():
    registry = MetadataRegistry()
    registry.register_bundle(".star", ConventionBundle("relion4"))
    registry.register_reader(".star", _Reader())

    assert [b.name for b in registry.bundles_for("x.star")] == ["relion4"]
    assert isinstance(registry.reader_for("x.star"), _Reader)


def test_a_named_reader_takes_the_place_of_the_registered_one():
    registry = MetadataRegistry()
    registry.register_reader([".star"], _Reader())
    named = _Reader()

    assert registry.read("x.star", reader=named).raw._reader is named


class _ClassNumber(ReadConvention):
    source_columns = ("_rlnClassNumber",)
    target_columns = ("class_number",)

    def matches(self, raw):
        return raw.has(*self.source_columns)

    def load(self, table):
        column = table.column("_rlnClassNumber")
        return {"class_number": pc.cast(column, pa.int64())}


def _lab_schema():
    particles = TableSchema(
        "particles",
        *PARTICLES.columns,
        ColumnDescriptor("class_number", pa.int64()),
    )
    return Schema(particles, OPTICS, relations=SCHEMA.relations_of("particles"))


def test_a_registry_of_your_own_reads_into_a_schema_of_your_own():
    registry = rxm.new_registry(_lab_schema())
    lab = ConventionBundle("lab", read={"particles": [_ClassNumber()]})
    registry.register_bundle(".star", lab)

    df = registry.read(SUBTOMO)["particles"].to_pandas()

    assert "class_number" in df.columns
    assert "coord_x" in df.columns
    assert "class_number" not in rxm.read(SUBTOMO)["particles"].to_pandas()


def test_results_hand_back_arrow_too():
    result = rxm.read(SUBTOMO)["particles"]

    pd.testing.assert_frame_equal(
        result.to_arrow().to_pandas(), result.to_pandas()
    )
    assert result.raw["particles"].to_arrow().num_rows == 57
