# SPDX-License-Identifier: LGPL-2.1-or-later

import shutil

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pytest

import rexlib_metadata as rxm
from rexlib_metadata import pose
from rexlib_metadata.abc import Reader, Writer
from rexlib_metadata.canonical import OPTICS, PARTICLES, SCHEMA
from rexlib_metadata.convention import (
    ConventionBundle,
    RawTable,
    ReadConvention,
)
from rexlib_metadata.conventions.relion import relion4_bundle
from rexlib_metadata.formats.star import StarReader, StarWriter
from rexlib_metadata.registry import MetadataRegistry
from rexlib_metadata.schema import ColumnDescriptor, Schema, TableSchema

from .support import STAR, SUBTOMO, mylab


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

    df = registry.read(str(SUBTOMO))["particles"].to_pandas()

    assert "class_number" in df.columns
    assert "coord_x" in df.columns
    assert "class_number" not in rxm.read(str(SUBTOMO))["particles"].to_pandas()


def test_results_hand_back_arrow_too():
    result = rxm.read(str(SUBTOMO))["particles"]

    arrow = result.to_arrow()
    frame = pa.Table.from_pandas(result.to_pandas(), preserve_index=False)
    assert frame.cast(arrow.schema).equals(arrow)
    assert result.raw["particles"].to_arrow().num_rows == arrow.num_rows


class _Writer(Writer):
    def write_tables(self, path, tables):
        pass


def test_the_registered_writer_is_the_one_handed_back():
    writer = _Writer()
    registry = MetadataRegistry()
    registry.register_writer([".star"], writer)

    assert registry.writer_for("x.star") is writer
    assert registry.writer_for("X.STAR") is writer
    with pytest.raises(ValueError, match=r"No writer registered for '\.xmd'"):
        registry.writer_for("x.xmd")


class _Recorder(Writer):
    def __init__(self) -> None:
        self.names: list[str] = []

    def write_tables(self, path, tables):
        self.names = [table.schema.table_name for table in tables]


def _unregistered(tmp_path):
    """A STAR file under an extension nothing is registered for."""
    path = tmp_path / "particles.txt"
    shutil.copy(STAR / "one_loop.star", path)
    return str(path)


def _star_read(path):
    return rxm.read(path, reader=StarReader(), bundle=relion4_bundle())


def test_an_unregistered_extension_reads_through_what_is_named(tmp_path):
    named = _star_read(_unregistered(tmp_path))
    registered = rxm.read(str(STAR / "one_loop.star"))

    pd.testing.assert_frame_equal(
        named["particles"].to_pandas(), registered["particles"].to_pandas()
    )


def test_a_named_reader_without_conventions_fills_nothing(tmp_path):
    result = rxm.read(_unregistered(tmp_path), reader=StarReader())
    particles = result["particles"]

    assert result.names == ()
    assert result.raw.names == ("particles",)
    with pytest.raises(ValueError, match="No convention fills"):
        particles.to_pandas()


def test_a_named_writer_writes_the_raw_tables(tmp_path):
    recorder = _Recorder()

    rxm.read(str(STAR / "one_loop.star")).raw.write(
        str(tmp_path / "out.csv"), writer=recorder
    )

    assert recorder.names == ["particles"]


def test_a_named_writer_writes_the_canonical_tables(tmp_path):
    out = str(tmp_path / "out.txt")

    _star_read(_unregistered(tmp_path)).write(
        out, writer=StarWriter(), bundle=relion4_bundle()
    )

    pd.testing.assert_frame_equal(
        _star_read(out)["particles"].to_pandas(),
        rxm.read(str(STAR / "one_loop.star"))["particles"].to_pandas(),
    )


def test_a_write_reads_the_source_again_through_the_named_reader(tmp_path):
    out = tmp_path / "out.star"

    _star_read(_unregistered(tmp_path)).write(str(out))

    assert rxm.read(str(out)).names == ("particles",)


def test_a_bundle_of_your_own_goes_in_front_of_relions():
    plain = rxm.read(str(SUBTOMO))["particles"].to_pandas()

    layered = rxm.read(str(SUBTOMO), bundle=[mylab(), relion4_bundle()])
    df = layered["particles"].to_pandas()

    a, origin = pose.relion(df["transform"])
    plain_a, plain_origin = pose.relion(plain["transform"])
    assert origin[0] == pytest.approx(plain_origin[0] + 1.0, abs=1e-5)
    assert a[0][0] == pytest.approx(plain_a[0][0])
    assert df["coord_x"].tolist() == plain["coord_x"].tolist()
