# SPDX-License-Identifier: LGPL-2.1-or-later

import shutil
from pathlib import Path

import pandas as pd
import pytest

import rexlib_metadata as rxm
from rexlib_metadata.abc import Writer
from rexlib_metadata.conventions.relion import relion4_bundle
from rexlib_metadata.formats.star import StarReader, StarWriter

FILES = Path(__file__).parent.parent / "files" / "star"


class _Recorder(Writer):
    def __init__(self) -> None:
        self.names: list[str] = []

    def write_tables(self, path, tables):
        self.names = [table.schema.table_name for table in tables]


def unregistered(tmp_path):
    """A STAR file under an extension nothing is registered for."""
    path = tmp_path / "particles.txt"
    shutil.copy(FILES / "one_loop.star", path)
    return str(path)


def star_read(path):
    return rxm.read(path, reader=StarReader(), bundle=relion4_bundle())


def test_an_unregistered_extension_reads_through_what_is_named(tmp_path):
    named = star_read(unregistered(tmp_path))
    registered = rxm.read(str(FILES / "one_loop.star"))

    pd.testing.assert_frame_equal(
        named["particles"].to_pandas(), registered["particles"].to_pandas()
    )


def test_a_named_reader_without_conventions_fills_nothing(tmp_path):
    result = rxm.read(unregistered(tmp_path), reader=StarReader())
    particles = result["particles"]

    assert result.names == ()
    assert result.raw.names == ("particles",)
    with pytest.raises(ValueError, match="No convention fills"):
        particles.to_pandas()


def test_an_unregistered_extension_without_a_reader_still_raises(tmp_path):
    path = unregistered(tmp_path)

    with pytest.raises(ValueError, match="No reader registered"):
        rxm.read(path)


def test_a_named_writer_writes_the_raw_tables(tmp_path):
    recorder = _Recorder()

    rxm.read(str(FILES / "one_loop.star")).raw.write(
        str(tmp_path / "out.csv"), writer=recorder
    )

    assert recorder.names == ["particles"]


def test_a_named_writer_writes_the_canonical_tables(tmp_path):
    out = str(tmp_path / "out.txt")

    star_read(unregistered(tmp_path)).write(
        out, writer=StarWriter(), bundle=relion4_bundle()
    )

    pd.testing.assert_frame_equal(
        star_read(out)["particles"].to_pandas(),
        rxm.read(str(FILES / "one_loop.star"))["particles"].to_pandas(),
    )


def test_a_write_reads_the_source_again_through_the_named_reader(tmp_path):
    out = tmp_path / "out.star"

    star_read(unregistered(tmp_path)).write(str(out))

    assert rxm.read(str(out)).names == ("particles",)
