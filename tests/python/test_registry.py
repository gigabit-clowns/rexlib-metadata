import pyarrow as pa
import pytest

from rexlib_metadata.abc import Reader
from rexlib_metadata.convention import ConventionBundle, RawTable
from rexlib_metadata.registry import MetadataRegistry


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

    assert registry.read("x.star")._reader is reader


def test_one_extension_may_be_given_as_a_string():
    registry = MetadataRegistry()
    registry.register_bundle(".star", ConventionBundle("relion4"))
    registry.register_reader(".star", _Reader())

    assert [b.name for b in registry.bundles_for("x.star")] == ["relion4"]
    assert isinstance(registry.reader_for("x.star"), _Reader)
