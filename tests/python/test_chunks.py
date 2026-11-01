# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import pandas as pd
import polars as pl
import pyarrow as pa
import pytest

import rexlib_metadata as rxm
from rexlib_metadata import ReadResult
from rexlib_metadata.abc import Reader
from rexlib_metadata.canonical import SCHEMA
from rexlib_metadata.convention import ConventionBundle, RawTable
from rexlib_metadata.conventions.relion import relion4_bundle
from rexlib_metadata.formats.star import StarReader
from rexlib_metadata.registry import MetadataRegistry

FILES = Path(__file__).parent.parent / "files" / "star"
COLUMNS = ("_rlnImageName", "_rlnCoordinateX", "_rlnCoordinateY")


def block(name, rows, first=0):
    header = f"data_{name}\n\nloop_\n" + "".join(f"{c}\n" for c in COLUMNS)
    body = "".join(
        f"{row:06d}@stack.mrcs {row}.5 {row}.25\n"
        for row in range(first + 1, first + rows + 1)
    )
    return header + body + "\n"


def file_of(tmp_path, content, name="made.star"):
    path = tmp_path / name
    path.write_text(content)
    return str(path)


def particles(path, **kwargs):
    return rxm.read(path, **kwargs)["particles"]


class _Closing(Reader):
    """A reader whose chunk stream records that it was closed."""

    def __init__(self):
        self.closed = False

    def read_tables(self, path):
        return [RawTable.of("particles", _fake_table(6))]

    def read_chunks(self, path, size, columns=None):
        try:
            yield from super().read_chunks(path, size, columns)
        finally:
            self.closed = True


def _fake_table(rows):
    return pa.table(
        {
            "_rlnImageName": [f"{r + 1:06d}@a.mrcs" for r in range(rows)],
            "_rlnCoordinateX": [f"{r}.0" for r in range(rows)],
            "_rlnCoordinateY": [f"{r}.5" for r in range(rows)],
        }
    )


def _registry(reader):
    registry = MetadataRegistry()
    registry.register_reader([".star"], reader)
    registry.register_bundle([".star"], relion4_bundle())
    return registry


class _CountingStar(StarReader):
    """A STAR reader that counts the times it reads a file whole."""

    def __init__(self):
        self.whole = 0

    def read_tables(self, path):
        self.whole += 1
        return super().read_tables(path)

    def read_tables_keeping(self, path, columns):
        self.whole += 1
        return super().read_tables_keeping(path, columns)


def test_naming_a_table_and_chunking_it_never_read_the_file_whole(tmp_path):
    path = file_of(tmp_path, block("particles", 2_000))
    reader = _CountingStar()
    result = _registry(reader).read(path)["particles"]

    assert reader.whole == 0

    rows = sum(len(chunk) for chunk in result.chunks(500))

    assert rows == 2_000
    assert reader.whole == 0


def test_a_hundred_thousand_rows_keep_their_count(tmp_path):
    path = file_of(tmp_path, block("particles", 100_000))
    result = particles(path)

    rows = sum(len(chunk) for chunk in result.chunks(10_000))

    assert rows == 100_000


def test_the_chunks_put_back_together_are_the_whole_read(tmp_path):
    path = file_of(tmp_path, block("particles", 2_500))
    result = particles(path)

    pieces = [chunk.to_pandas() for chunk in result.chunks(700)]

    pd.testing.assert_frame_equal(
        pd.concat(pieces, ignore_index=True), result.to_pandas()
    )


def test_a_chunk_is_the_rows_and_the_name_and_nothing_else(tmp_path):
    path = file_of(tmp_path, block("particles", 3))

    chunk = next(particles(path).chunks(2))

    assert chunk.name == "particles"
    assert len(chunk) == 2
    assert isinstance(chunk.to_arrow(), pa.Table)
    assert isinstance(chunk.to_pandas(), pd.DataFrame)
    assert isinstance(chunk.to_polars(), pl.DataFrame)
    assert not hasattr(chunk, "write")


def test_only_the_columns_asked_for_cross_over(tmp_path):
    path = file_of(tmp_path, block("particles", 5))
    result = particles(path, columns=["coord_x"])

    chunk = next(result.chunks(2))

    assert chunk.to_pandas().columns.tolist() == ["coord_x"]


def test_a_result_of_more_than_one_table_asks_which_one(tmp_path):
    result = rxm.read(file_of(tmp_path, block("particles", 3)))

    with pytest.raises(ValueError, match=r"result\[name\]"):
        result.chunks(2)


def test_only_the_block_that_fills_the_table_is_read(tmp_path):
    content = block("particles", 4) + block("particles", 4, first=100)
    path = file_of(tmp_path, content)
    result = particles(path)

    pieces = [chunk.to_pandas() for chunk in result.chunks(3)]

    pd.testing.assert_frame_equal(
        pd.concat(pieces, ignore_index=True), result.to_pandas()
    )
    assert sum(len(c) for c in result.chunks(3)) == 4


def test_a_table_no_convention_fills_says_so(tmp_path):
    path = file_of(tmp_path, block("particles", 3))
    raw = rxm.read(path).raw
    narrowed = ReadResult(
        raw, [ConventionBundle("none")], SCHEMA, "particles"
    )

    stream = narrowed.chunks(2)

    with pytest.raises(ValueError, match="No convention fills"):
        next(stream)


def test_the_stream_is_closed_when_it_runs_out():
    reader = _Closing()
    result = _registry(reader).read("x.star")["particles"]

    assert sum(len(chunk) for chunk in result.chunks(2)) == 6
    assert reader.closed


def test_the_stream_is_closed_when_it_is_abandoned():
    reader = _Closing()
    result = _registry(reader).read("x.star")["particles"]
    stream = result.chunks(2)

    next(stream)
    stream.close()

    assert reader.closed


def test_a_reader_that_cannot_stream_is_chunked_for_it():
    reader = _Closing()
    result = _registry(reader).read("x.star")["particles"]

    assert [len(chunk) for chunk in result.chunks(4)] == [4, 2]


def test_the_star_reader_streams_rather_than_slicing():
    assert StarReader.read_chunks is not Reader.read_chunks


PARTICLES_FIRST = (
    "data_particles\n\nloop_\n_rlnImageName\n_rlnOpticsGroup\n"
    "000001@a.mrcs 1\n000002@a.mrcs 1\n\n"
    "data_optics\n\nloop_\n_rlnOpticsGroup\n_rlnImagePixelSize\n1 1.5\n"
)


@pytest.mark.parametrize(
    "columns",
    [
        pytest.param(None, id="every-column"),
        pytest.param(["pixel_size"], id="narrowed"),
    ],
)
def test_optics_come_from_their_block_when_the_particles_come_first(
    tmp_path, columns
):
    path = file_of(tmp_path, PARTICLES_FIRST)
    optics = rxm.read(path, columns=columns)["optics"]

    whole = optics.to_pandas()
    chunked = pd.concat(chunk.to_pandas() for chunk in optics.chunks(10))

    assert whole["pixel_size"].tolist() == [1.5]
    pd.testing.assert_frame_equal(chunked, whole)


def test_a_chunked_read_skips_the_blocks_before_its_own(tmp_path):
    before = "data_empty\n\ndata_general\n_rlnVoltage 300\n\n"
    path = file_of(tmp_path, before + block("particles", 3))
    result = particles(path)

    chunked = pd.concat(chunk.to_pandas() for chunk in result.chunks(2))

    pd.testing.assert_frame_equal(
        chunked.reset_index(drop=True), result.to_pandas()
    )


def test_a_block_holding_both_tables_fills_both(tmp_path):
    content = (
        "data_\n\nloop_\n_rlnImageName\n_rlnOpticsGroup\n"
        "_rlnImagePixelSize\n000001@a.mrcs 1 1.5\n"
    )
    result = rxm.read(file_of(tmp_path, content))

    assert result.names == ("particles", "optics")
    (chunk,) = result["optics"].chunks(5)
    assert chunk.to_pandas()["pixel_size"].tolist() == [1.5]

