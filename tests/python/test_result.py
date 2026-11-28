# SPDX-License-Identifier: LGPL-2.1-or-later

import shutil
from pathlib import Path

import pandas as pd
import polars as pl
import pyarrow as pa
import pytest

import rexlib_metadata as rxm
from rexlib_metadata import ReadResult
from rexlib_metadata.abc import Reader, Writer
from rexlib_metadata.canonical import SCHEMA
from rexlib_metadata.convention import ConventionBundle, RawTable
from rexlib_metadata.conventions.relion import relion4_bundle
from rexlib_metadata.engine import source_columns
from rexlib_metadata.formats.star import StarReader
from rexlib_metadata.registry import MetadataRegistry

from .support import STAR, SUBTOMO, CountingStar, registry_of


class _Failing(Writer):
    def write_tables(self, path, tables):
        Path(path).write_text("half a file")
        raise RuntimeError("the disk filled up")


class _Plain(Reader):
    def read_tables(self, path):
        return StarReader().read_tables(path)


class _Spy(StarReader):
    def __init__(self):
        self.kept = []

    def read_tables(self, path):
        raise AssertionError("a projected read parsed every column")

    def read_tables_keeping(self, path, columns):
        self.kept.append(columns)
        return super().read_tables_keeping(path, columns)


def _copy(name, tmp_path):
    return str(shutil.copy(STAR / name, tmp_path / name))


def test_two_columns_read_and_one_changed_write_back_all_of_them(tmp_path):
    source = str(STAR / "one_loop.star")
    result = rxm.read(source, columns=["coord_x", "coord_y"])
    df = result.to_pandas()
    df["coord_x"] += 10
    out = str(tmp_path / "out.star")

    result.updated(df).write(out)

    before = rxm.read(source).raw.to_pandas()
    after = rxm.read(out).raw.to_pandas()
    assert set(after.columns) >= set(before.columns)
    assert after["_rlnCoordinateX"].astype(float).tolist() == pytest.approx(
        (before["_rlnCoordinateX"].astype(float) + 10).tolist()
    )
    pd.testing.assert_frame_equal(
        rxm.read(out).to_pandas().drop(columns="coord_x"),
        rxm.read(source).to_pandas().drop(columns="coord_x"),
    )


def test_a_projection_shows_the_columns_asked_for_in_that_order():
    result = rxm.read(
        str(STAR / "one_loop.star"), columns=["coord_y", "image_path"]
    )

    assert result.to_pandas().columns.tolist() == ["coord_y", "image_path"]


@pytest.mark.parametrize(
    ("columns", "names"),
    [
        pytest.param(["coord_x"], ("particles",), id="particles"),
        pytest.param(["voltage"], ("optics",), id="optics"),
        pytest.param(
            ["coord_x", "voltage"], ("particles", "optics"), id="both"
        ),
    ],
)
def test_a_projection_names_the_tables_that_declare_a_column(columns, names):
    result = rxm.read(str(STAR / "rln3.1_data_style.star"), columns=columns)

    assert result.names == names


def test_a_column_no_table_declares_raises_before_the_file_is_opened(
    tmp_path,
):
    with pytest.raises(ValueError, match="No canonical table declares 'x'"):
        rxm.read(str(tmp_path / "missing.star"), columns=["x"])


def test_a_column_the_file_does_not_hold_raises():
    result = rxm.read(
        str(STAR / "rln3.1_data_style.star"), columns=["transform"]
    )

    with pytest.raises(ValueError, match="holds no 'transform'"):
        result.to_pandas()


def test_a_view_of_one_table_writes_every_table(tmp_path):
    out = str(tmp_path / "out.star")

    rxm.read(str(STAR / "rln3.1_data_style.star"))["particles"].write(out)

    assert rxm.read(out).names == ("particles", "optics")


def test_updates_of_another_length_raise(tmp_path):
    result = rxm.read(str(STAR / "one_loop.star"), columns=["coord_x"])
    edited = result.updated(result.to_pandas().head(1))
    out = str(tmp_path / "out.star")

    with pytest.raises(ValueError, match="one per row kept"):
        edited.write(out)


def test_updates_go_to_the_table_the_view_shows(tmp_path):
    result = rxm.read(str(STAR / "rln3.1_data_style.star"))["optics"]
    df = result.to_pandas()
    df["voltage"] = 200.0
    out = str(tmp_path / "out.star")

    result.updated(df).write(out)

    assert rxm.read(out)["optics"].to_pandas()["voltage"].tolist() == [200.0]


def test_updates_may_be_polars(tmp_path):
    result = rxm.read(str(STAR / "one_loop.star"), columns=["coord_x"])
    df = result.to_polars().with_columns(pl.col("coord_x") * 0)
    out = str(tmp_path / "out.star")

    result.updated(df).write(out)

    x = rxm.read(out, columns=["coord_x"]).to_pandas()["coord_x"]
    assert set(x) == {0.0}


def test_a_result_writes_over_its_own_source(tmp_path):
    path = _copy("one_loop.star", tmp_path)
    result = rxm.read(path, columns=["coord_x"])
    df = result.to_pandas()
    df["coord_x"] = 1.0

    result.updated(df).write(path)

    assert set(rxm.read(path).to_pandas()["coord_x"]) == {1.0}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["one_loop.star"]


def test_a_failed_write_leaves_the_destination_as_it_was(tmp_path):
    registry = MetadataRegistry()
    registry.register_reader([".star"], StarReader())
    registry.register_writer([".star"], _Failing())
    registry.register_bundle([".star"], relion4_bundle())
    path = _copy("one_loop.star", tmp_path)
    before = Path(path).read_bytes()
    result = registry.read(path)

    with pytest.raises(RuntimeError, match="disk filled up"):
        result.write(path)

    assert Path(path).read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["one_loop.star"]


def test_the_raw_columns_kept_are_those_read_into_what_was_asked():
    kept = source_columns(["coord_x"], [relion4_bundle()], SCHEMA)

    assert {"_rlnCoordinateX", "_rlnCoordinateY", "_rlnImageName"} <= kept
    assert "_rlnAngleRot" not in kept
    assert "_rlnVoltage" not in kept


def test_a_projected_read_parses_only_the_columns_it_keeps():
    reader = _Spy()
    path = str(STAR / "rln3.1_data_style.star")

    frame = registry_of(reader).read(path, columns=["coord_x"]).to_pandas()

    assert reader.kept == [
        source_columns(["coord_x"], [relion4_bundle()], SCHEMA)
    ]
    assert frame["coord_x"].tolist() == (
        rxm.read(path)["particles"].to_pandas()["coord_x"].tolist()
    )


def test_a_reader_that_cannot_narrow_a_read_is_narrowed_after_it():
    path = str(STAR / "rln3.1_data_style.star")
    whole = _Plain().read_tables(path)

    kept = _Plain().read_tables_keeping(
        path, {"_rlnCoordinateX", "_rlnNoSuchColumn"}
    )

    assert [t.schema.table_name for t in kept] == [
        t.schema.table_name for t in whole
    ]
    assert [t.table.num_rows for t in kept] == [
        t.table.num_rows for t in whole
    ]
    assert {n for t in kept for n in t.schema.column_names} == {
        "_rlnCoordinateX"
    }


@pytest.mark.parametrize(
    "name", sorted(p.name for p in STAR.glob("*.star")), ids=str
)
def test_the_parser_keeps_what_a_read_and_a_select_would(name):
    path = str(STAR / name)
    columns = {"_rlnImageName", "_rlnAngleRot", "_rlnVoltage"}

    assert StarReader().read_tables_keeping(path, columns) == (
        _Plain().read_tables_keeping(path, columns)
    )


def test_a_canonical_read_keeps_nothing_of_the_file():
    reader = CountingStar()
    result = rxm.read(str(STAR / "one_loop.star"), reader=reader)

    result["particles"].to_pandas()
    result["particles"].to_pandas()
    result.raw.to_pandas()
    result.raw.to_pandas()

    assert reader.whole == 3


_TWO_FILLERS = """data_a
loop_
_rlnImageName
_rlnCoordinateX
_rlnCoordinateY
1@a 1 1
2@a 2 2
3@a 3 3

data_b
loop_
_rlnImageName
_rlnCoordinateX
_rlnCoordinateY
_rlnCtfMaxResolution
1@b 10 10 4
2@b 20 20 4
"""


def test_a_narrowed_read_takes_the_block_a_full_read_takes(tmp_path):
    path = tmp_path / "two.star"
    path.write_text(_TWO_FILLERS)

    full = rxm.read(str(path))["particles"].to_pandas()
    narrowed = rxm.read(str(path), columns=["coord_x"])["particles"]

    assert narrowed.to_pandas()["coord_x"].tolist() == full["coord_x"].tolist()


def test_a_narrowed_read_writes_back_into_its_own_block(tmp_path):
    path = tmp_path / "two.star"
    path.write_text(_TWO_FILLERS)
    out = str(tmp_path / "out.star")
    view = rxm.read(str(path), columns=["coord_x"])["particles"]
    frame = view.to_pandas()
    frame["coord_x"] += 0.5

    view.updated(frame).write(out)

    written = rxm.read(out).raw
    kept = written["a"].to_pandas()["_rlnCoordinateX"]
    assert kept.tolist() == ["1", "2", "3"]
    particles = written["particles"].to_pandas()
    assert particles["_rlnCoordinateX"].tolist() == ["10.5", "20.5"]


@pytest.mark.parametrize(
    ("updates", "error"),
    [
        pytest.param(
            {"foo": [1.0]}, "'foo', which no table of 'particles'", id="unknown"
        ),
        pytest.param(
            {"optics_group": [1.5]}, "'optics_group' holds a value", id="lossy"
        ),
    ],
)
def test_updates_that_cannot_be_written_raise_before_anything_is(
    tmp_path, updates, error
):
    view = rxm.read(str(STAR / "relion3.1_subtomo.star"))["particles"]
    rows = len(view.to_pandas())
    frame = pa.table({k: v * rows for k, v in updates.items()})
    out = tmp_path / "out.star"
    edited = view.updated(frame)

    with pytest.raises(ValueError, match=error):
        edited.write(str(out))
    assert not out.exists()


def test_a_raw_table_reads_alone_however_it_is_read():
    raw = rxm.read(str(STAR / "rln3.1_data_style.star")).raw
    second = raw.names[1]
    view = raw[second]

    chunks = list(view._chunks(1000))
    whole = view._reread()

    assert [ordinal for ordinal, _ in chunks] == [0]
    assert chunks[0][1].table.equals(raw[second].to_arrow())
    assert [table.schema.table_name for table in whole] == [second]


COLUMNS = ("_rlnImageName", "_rlnCoordinateX", "_rlnCoordinateY")


def _block(name, rows, first=0):
    header = f"data_{name}\n\nloop_\n" + "".join(f"{c}\n" for c in COLUMNS)
    body = "".join(
        f"{row:06d}@stack.mrcs {row}.5 {row}.25\n"
        for row in range(first + 1, first + rows + 1)
    )
    return header + body + "\n"


def _file_of(tmp_path, content, name="made.star"):
    path = tmp_path / name
    path.write_text(content)
    return str(path)


def _particles(path, **kwargs):
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


def test_naming_a_table_and_chunking_it_never_read_the_file_whole(tmp_path):
    path = _file_of(tmp_path, _block("particles", 2_000))
    reader = CountingStar()
    result = registry_of(reader).read(path)["particles"]

    assert reader.whole == 0

    rows = sum(len(chunk) for chunk in result.chunks(500))

    assert rows == 2_000
    assert reader.whole == 0


def test_a_hundred_thousand_rows_keep_their_count(tmp_path):
    path = _file_of(tmp_path, _block("particles", 100_000))
    result = _particles(path)

    rows = sum(len(chunk) for chunk in result.chunks(10_000))

    assert rows == 100_000


def test_the_chunks_put_back_together_are_the_whole_read(tmp_path):
    path = _file_of(tmp_path, _block("particles", 2_500))
    result = _particles(path)

    pieces = [chunk.to_pandas() for chunk in result.chunks(700)]

    pd.testing.assert_frame_equal(
        pd.concat(pieces, ignore_index=True), result.to_pandas()
    )


def test_a_chunk_is_the_rows_and_the_name_and_nothing_else(tmp_path):
    path = _file_of(tmp_path, _block("particles", 3))

    chunk = next(_particles(path).chunks(2))

    assert chunk.name == "particles"
    assert len(chunk) == 2
    assert isinstance(chunk.to_arrow(), pa.Table)
    assert isinstance(chunk.to_pandas(), pd.DataFrame)
    assert isinstance(chunk.to_polars(), pl.DataFrame)
    assert not hasattr(chunk, "write")


def test_only_the_columns_asked_for_cross_over(tmp_path):
    path = _file_of(tmp_path, _block("particles", 5))
    result = _particles(path, columns=["coord_x"])

    chunk = next(result.chunks(2))

    assert chunk.to_pandas().columns.tolist() == ["coord_x"]


def test_a_result_of_more_than_one_table_asks_which_one(tmp_path):
    result = rxm.read(_file_of(tmp_path, _block("particles", 3)))

    with pytest.raises(ValueError, match=r"result\[name\]"):
        result.chunks(2)


def test_only_the_block_that_fills_the_table_is_read(tmp_path):
    content = _block("particles", 4) + _block("particles", 4, first=100)
    path = _file_of(tmp_path, content)
    result = _particles(path)

    pieces = [chunk.to_pandas() for chunk in result.chunks(3)]

    pd.testing.assert_frame_equal(
        pd.concat(pieces, ignore_index=True), result.to_pandas()
    )
    assert sum(len(c) for c in result.chunks(3)) == 4


def test_a_table_no_convention_fills_says_so(tmp_path):
    path = _file_of(tmp_path, _block("particles", 3))
    raw = rxm.read(path).raw
    narrowed = ReadResult(
        raw, [ConventionBundle("none")], SCHEMA, "particles"
    )

    stream = narrowed.chunks(2)

    with pytest.raises(ValueError, match="No convention fills"):
        next(stream)


def test_the_stream_is_closed_when_it_runs_out():
    reader = _Closing()
    result = registry_of(reader).read("x.star")["particles"]

    assert sum(len(chunk) for chunk in result.chunks(2)) == 6
    assert reader.closed


def test_the_stream_is_closed_when_it_is_abandoned():
    reader = _Closing()
    result = registry_of(reader).read("x.star")["particles"]
    stream = result.chunks(2)

    next(stream)
    stream.close()

    assert reader.closed


def test_a_reader_that_cannot_stream_is_chunked_for_it():
    reader = _Closing()
    result = registry_of(reader).read("x.star")["particles"]

    assert [len(chunk) for chunk in result.chunks(4)] == [4, 2]


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
    path = _file_of(tmp_path, PARTICLES_FIRST)
    optics = rxm.read(path, columns=columns)["optics"]

    whole = optics.to_pandas()
    chunked = pd.concat(chunk.to_pandas() for chunk in optics.chunks(10))

    assert whole["pixel_size"].tolist() == [1.5]
    pd.testing.assert_frame_equal(chunked, whole)


def test_a_chunked_read_skips_the_blocks_before_its_own(tmp_path):
    before = "data_empty\n\ndata_general\n_rlnVoltage 300\n\n"
    path = _file_of(tmp_path, before + _block("particles", 3))
    result = _particles(path)

    chunked = pd.concat(chunk.to_pandas() for chunk in result.chunks(2))

    pd.testing.assert_frame_equal(
        chunked.reset_index(drop=True), result.to_pandas()
    )


def _both(tmp_path, *rows):
    header = (
        "data_\n\nloop_\n_rlnImageName\n_rlnOpticsGroup\n_rlnImagePixelSize\n"
    )
    body = "".join(f"{row}\n" for row in rows)
    return rxm.read(_file_of(tmp_path, header + body))


def test_a_block_holding_both_tables_fills_both_one_row_per_group(tmp_path):
    result = _both(tmp_path, "1@a.mrcs 1 1.5", "2@a.mrcs 1 1.5")

    assert result.names == ("particles", "optics")
    assert result["optics"].to_pandas()["pixel_size"].tolist() == [1.5]
    assert [len(c) for c in result["optics"].chunks(1)] == [1]


def test_rows_of_one_group_that_disagree_are_refused(tmp_path):
    result = _both(tmp_path, "1@a.mrcs 1 1.5", "2@a.mrcs 1 2.0")

    with pytest.raises(ValueError, match="disagree on 'pixel_size'"):
        result["optics"].to_pandas()


@pytest.fixture(params=[".star", ".sqlite"], ids=["star", "sqlite"])
def _subtomo(request, tmp_path):
    if request.param == ".star":
        return str(SUBTOMO)
    path = str(tmp_path / f"subtomo{request.param}")
    rxm.read(str(SUBTOMO)).raw.write(path)
    return path


@pytest.mark.parametrize("size", [0, -1], ids=["zero", "negative"])
def test_a_chunk_of_no_rows_is_refused(_subtomo, size):
    result = rxm.read(_subtomo, bundle=relion4_bundle())
    particles = result["particles"]

    with pytest.raises(ValueError, match="at least one row"):
        particles.chunks(size)
