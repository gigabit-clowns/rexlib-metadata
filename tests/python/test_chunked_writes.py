# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import pyarrow as pa
import pytest

import rexlib_metadata as rxm
from rexlib_metadata import result as result_module
from rexlib_metadata.abc import Writer
from rexlib_metadata.convention import RawTable
from rexlib_metadata.formats.star import StarWriter
from rexlib_metadata.result import RawResult

FILES = Path(__file__).parent.parent / "files"
SUBTOMO = FILES / "star" / "relion3.1_subtomo.star"
POLISHED = FILES / "star" / "relion3.0_polished.star"


def _plain(_):
    return {}


def _shifted(view):
    frame = view.to_pandas()
    frame["shift_x"] += 1.5
    return {"updates": frame[["shift_x"]]}


def _every_third(view):
    return {"rows": list(range(0, len(view.to_pandas()), 3))}


def _a_mask(view):
    return {"rows": [n % 2 == 0 for n in range(len(view.to_pandas()))]}


def _kept_and_shifted(view):
    frame = view.to_pandas().iloc[::3].copy()
    frame["shift_x"] -= 2.0
    return {"rows": frame.index, "updates": frame[["shift_x"]]}


def _backwards(view):
    return {"rows": list(range(len(view.to_pandas())))[::-1]}


CASES = [
    pytest.param(SUBTOMO, ".star", "particles", _plain, id="star"),
    pytest.param(SUBTOMO, ".xmd", "particles", _plain, id="optics-folded"),
    pytest.param(SUBTOMO, ".star", "particles", _shifted, id="updates"),
    pytest.param(SUBTOMO, ".star", "particles", _every_third, id="positions"),
    pytest.param(SUBTOMO, ".xmd", "particles", _a_mask, id="mask-folded"),
    pytest.param(SUBTOMO, ".star", "particles", _kept_and_shifted, id="both"),
    pytest.param(SUBTOMO, ".star", "particles", _backwards, id="backwards"),
    pytest.param(SUBTOMO, ".star", "optics", _plain, id="optics"),
    pytest.param(POLISHED, ".star", "particles", _plain, id="shared"),
]


def _written(view, out, write, rows_per_chunk, monkeypatch):
    with monkeypatch.context() as patched:
        patched.setattr(result_module, "_WRITTEN_ROWS", rows_per_chunk)
        view.write(str(out), **write)
    return out.read_bytes()


@pytest.mark.parametrize(("source", "suffix", "name", "edit"), CASES)
def test_a_file_written_in_chunks_is_the_file_written_whole(
    tmp_path, monkeypatch, source, suffix, name, edit
):
    view = rxm.read(str(source))[name]
    write = edit(view)

    chunked = _written(view, tmp_path / f"c{suffix}", write, 2, monkeypatch)
    monkeypatch.setattr(StarWriter, "write_chunks", Writer.write_chunks)
    whole = _written(view, tmp_path / f"w{suffix}", write, 10**9, monkeypatch)

    assert chunked == whole


@pytest.mark.parametrize(
    "edit",
    [
        pytest.param(_plain, id="plain"),
        pytest.param(_shifted, id="updates"),
        pytest.param(_a_mask, id="mask"),
        pytest.param(_every_third, id="positions"),
    ],
)
def test_a_streamed_write_never_reads_the_source_whole(
    tmp_path, monkeypatch, edit
):
    view = rxm.read(str(SUBTOMO))["particles"]
    write = edit(view)

    with monkeypatch.context() as patched:
        patched.setattr(RawResult, "reread", _refused)
        view.write(str(tmp_path / "out.star"), **write)

    assert len(rxm.read(str(tmp_path / "out.star"))["particles"].to_pandas())


def _refused(_):
    raise AssertionError("the source was read whole")


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        pytest.param([True, False], "mask of 2 where table", id="mask"),
        pytest.param([0, 57], "outside table 'particles'", id="outside"),
    ],
)
def test_rows_that_do_not_fit_a_streamed_table_leave_no_file(
    tmp_path, rows, message
):
    out = tmp_path / "out.star"

    with pytest.raises(ValueError, match=message):
        rxm.read(str(SUBTOMO))["particles"].write(str(out), rows=rows)

    assert list(tmp_path.iterdir()) == []


def test_the_default_gathers_the_chunks_of_each_table(tmp_path):
    written: list[RawTable] = []

    class _Recorder(Writer):
        def write_tables(self, path, tables):
            written.extend(tables)

    one = pa.table({"_a": ["1"]})
    _Recorder().write_chunks(
        "x",
        [
            (0, RawTable.of("p", one)),
            (0, RawTable.of("p", one)),
            (1, RawTable.of("p", one)),
        ],
    )

    assert [(t.schema.table_name, t.table.num_rows) for t in written] == [
        ("p", 2),
        ("p", 1),
    ]


def test_a_star_file_written_in_chunks_reads_back_whole(tmp_path):
    out = tmp_path / "out.star"
    rows = pa.table({"_rlnA": ["1", "2", "3"]})

    StarWriter().write_chunks(
        str(out),
        [
            (0, RawTable.of("a", rows.slice(0, 2))),
            (0, RawTable.of("a", rows.slice(2))),
            (1, RawTable.of("b", rows.slice(0, 0))),
        ],
    )

    again = rxm.read(str(out)).raw
    assert again.names == ("a", "b")
    assert again["a"].to_arrow().column("_rlnA").to_pylist() == ["1", "2", "3"]
    assert again["b"].to_arrow().num_rows == 0


def test_a_star_write_failing_midway_leaves_no_file(tmp_path):
    out = tmp_path / "out.star"

    def chunks():
        yield 0, RawTable.of("a", pa.table({"_rlnA": ["1"]}))
        raise RuntimeError("the source went away")

    with pytest.raises(RuntimeError, match="went away"):
        StarWriter().write_chunks(str(out), chunks())

    assert not out.exists()
