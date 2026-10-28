# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import pandas as pd
import pytest

import rexlib_metadata as rxm
from rexlib_metadata.abc import Reader, Writer
from rexlib_metadata.convention import ConventionBundle, RawTable
from rexlib_metadata.conventions.relion import relion4_bundle
from rexlib_metadata.conventions.star import StarReader
from rexlib_metadata.registry import MetadataRegistry

FILES = Path(__file__).parent.parent / "files" / "star"


class _Recorder(Writer):
    def __init__(self) -> None:
        self.tables: list[RawTable] = []

    def write_tables(self, path, tables):
        self.tables = list(tables)


def written(name, tmp_path):
    source = rxm.read(str(FILES / name))
    out = tmp_path / "out.star"
    source.write(str(out))
    return source, rxm.read(str(out))


def test_a_canonical_table_writes_back_the_same(tmp_path):
    source, again = written("one_loop.star", tmp_path)

    pd.testing.assert_frame_equal(
        source["particles"].to_pandas(), again["particles"].to_pandas()
    )


def test_every_canonical_table_becomes_its_own_block(tmp_path):
    source, again = written("rln3.1_data_style.star", tmp_path)

    assert again.names == ("particles", "optics")
    assert again.raw.names == ("particles", "optics")
    for name in source.names:
        pd.testing.assert_frame_equal(
            source[name].to_pandas(), again[name].to_pandas()
        )


def test_a_column_no_convention_writes_is_carried_over(tmp_path):
    source, again = written("one_loop.star", tmp_path)

    before = set(source.raw.to_pandas().columns)
    after = set(again.raw.to_pandas().columns)

    assert {"_rlnCtfImage", "_rlnMagnification"} <= before
    assert before <= after


def test_a_reference_that_had_an_index_comes_back_as_it_was(tmp_path):
    source, again = written("rln3.1_data_style.star", tmp_path)

    assert (
        again.raw["particles"].to_pandas()["_rlnImageName"].tolist()
        == source.raw["block_2"].to_pandas()["_rlnImageName"].tolist()
    )


def test_a_bare_path_comes_back_carrying_the_first_index(tmp_path):
    _, again = written("one_loop.star", tmp_path)

    names = again.raw.to_pandas()["_rlnImageName"]

    assert names[0] == "000001@" + names[0].split("@")[1]
    assert names[0].endswith("tomo_ts01.mrc_0000000_5.00A.mrc")


def test_a_number_is_written_as_short_as_it_can_be(tmp_path):
    _, again = written("rln3.1_data_style.star", tmp_path)

    particles = again.raw["particles"].to_pandas()
    optics = again.raw["optics"].to_pandas()

    assert particles["_rlnCoordinateX"].tolist() == ["587", "685"]
    assert optics["_rlnSphericalAberration"][0] == "2.7"


def test_a_bundle_of_your_own_writes_instead(tmp_path):
    source = rxm.read(str(FILES / "one_loop.star"))
    coordinates_only = ConventionBundle(
        "mylab",
        write={
            "particles": [
                c
                for c in relion4_bundle().write_conventions("particles")
                if c.target_columns == ("_rlnCoordinateX", "_rlnCoordinateY")
            ]
        },
    )
    out = tmp_path / "out.star"

    source.write(str(out), bundle=coordinates_only)
    df = rxm.read(str(out)).raw.to_pandas()

    assert df["_rlnCoordinateX"].tolist()[:2] == ["1572.444", "1507.5"]
    assert df["_rlnImageName"].tolist() == (
        source.raw.to_pandas()["_rlnImageName"].tolist()
    )


def test_a_destination_of_another_format_carries_nothing_over(tmp_path):
    recorder = _Recorder()
    registry = MetadataRegistry()
    registry.register_reader([".star"], StarReader())
    registry.register_writer([".xmd"], recorder)
    registry.register_bundle([".xmd"], relion4_bundle())
    registry.register_bundle([".star"], relion4_bundle())

    registry.read(str(FILES / "one_loop.star")).write(str(tmp_path / "o.xmd"))

    columns = recorder.tables[0].table.column_names
    assert "_rlnCoordinateX" in columns
    assert "_rlnCtfImage" not in columns


def test_a_table_no_convention_writes_says_so(tmp_path):
    source = rxm.read(str(FILES / "one_loop.star"))

    nothing = ConventionBundle("none")

    with pytest.raises(ValueError, match="writes canonical table"):
        source.write(str(tmp_path / "out.star"), bundle=nothing)


def test_an_extension_with_no_writer_raises(tmp_path):
    source = rxm.read(str(FILES / "one_loop.star"))

    with pytest.raises(ValueError, match="No writer registered"):
        source.write(str(tmp_path / "out.csv"))


def test_a_reader_is_still_all_a_format_needs_to_be_read():
    assert issubclass(StarReader, Reader)
