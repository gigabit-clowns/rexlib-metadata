from rexlib_metadata.convention import ConventionBundle
from rexlib_metadata.registry import MetadataRegistry


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
    try:
        registry.reader_for("data.csv")
    except ValueError as error:
        assert "No reader registered" in str(error)
    else:
        raise AssertionError("expected a ValueError")
