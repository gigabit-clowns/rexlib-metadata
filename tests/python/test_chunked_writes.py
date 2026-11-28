# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

import rexlib_metadata as rxm
from rexlib_metadata import result as result_module
from rexlib_metadata.abc import Writer
from rexlib_metadata.convention import RawTable
from rexlib_metadata.formats.star import StarWriter
from rexlib_metadata.result import RawResult, ReadResult

FILES = Path(__file__).parent.parent / "files"
SUBTOMO = FILES / "star" / "relion3.1_subtomo.star"
POLISHED = FILES / "star" / "relion3.0_polished.star"
CS = FILES / "cs" / "J114_particles_exported.cs"


def _moved(transforms, by):
    along_x = np.eye(1, 12, 3)[0]
    return [transform + by * along_x for transform in transforms]


def _plain(_):
    return {}


def _shifted(view):
    frame = view.to_pandas()
    frame["transform"] = _moved(frame["transform"], 1.5)
    return {"updates": frame[["transform"]]}


def _every_third(view):
    return {"rows": list(range(0, len(view.to_pandas()), 3))}


def _a_mask(view):
    return {"rows": [n % 2 == 0 for n in range(len(view.to_pandas()))]}


def _kept_and_shifted(view):
    frame = view.to_pandas().iloc[::3].copy()
    frame["transform"] = _moved(frame["transform"], -2.0)
    return {"rows": frame.index, "updates": frame[["transform"]]}


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
    pytest.param(POLISHED, ".star", "particles", _plain, id="relion30"),
    pytest.param(POLISHED, ".xmd", "particles", _a_mask, id="relion30-xmd"),
    pytest.param(POLISHED, ".star", "optics", _plain, id="relion30-optics"),
    pytest.param(CS, ".star", "particles", _plain, id="cs"),
    pytest.param(CS, ".xmd", "particles", _a_mask, id="cs-xmd"),
    pytest.param(CS, ".star", "particles", _kept_and_shifted, id="cs-both"),
]


def _written(view, out, write, rows_per_chunk, monkeypatch):
    with monkeypatch.context() as patched:
        patched.setattr(result_module, "_ROWS", rows_per_chunk)
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
    monkeypatch.setattr(ReadResult, "_whole_needed", lambda *_: True)
    whole = _written(view, tmp_path / f"w{suffix}", write, 10**9, monkeypatch)

    assert chunked == whole


def _two_settings(tmp_path):
    """Relion 3.0's fixture, its last rows on a second microscope setting."""
    lines = POLISHED.read_text().splitlines()
    names = [line.split()[0] for line in lines if line.startswith("_rln")]
    first = max(i for i, line in enumerate(lines) if line.startswith("_rln"))
    rows = [line.split() for line in lines[first + 1 :] if line.strip()]
    voltage = names.index("_rlnVoltage")
    for row in rows[len(rows) // 2 :]:
        row[voltage] = "200"
    path = tmp_path / "two.star"
    body = [" ".join(row) for row in rows]
    path.write_text("\n".join([*lines[: first + 1], *body]) + "\n")
    return path


@pytest.mark.parametrize(
    "rows",
    [
        pytest.param([0, 1], id="first-setting"),
        pytest.param([7, 8], id="second-setting"),
        pytest.param([n < 5 for n in range(10)], id="mask"),
    ],
)
def test_relion30_with_two_settings_writes_in_chunks_as_whole(
    tmp_path, monkeypatch, rows
):
    view = rxm.read(str(_two_settings(tmp_path)))["particles"]
    write = {"rows": rows}

    chunked = _written(view, tmp_path / "c.star", write, 2, monkeypatch)
    monkeypatch.setattr(StarWriter, "write_chunks", Writer.write_chunks)
    monkeypatch.setattr(ReadResult, "_whole_needed", lambda *_: True)
    whole = _written(view, tmp_path / "w.star", write, 10**9, monkeypatch)

    assert chunked == whole
    groups = rxm.read(str(tmp_path / "c.star"))["optics"].to_pandas()
    assert groups["optics_group"].tolist() == [1, 2]


@pytest.mark.parametrize(
    ("source", "edit"),
    [
        pytest.param(SUBTOMO, _plain, id="plain"),
        pytest.param(SUBTOMO, _shifted, id="updates"),
        pytest.param(SUBTOMO, _a_mask, id="mask"),
        pytest.param(SUBTOMO, _every_third, id="positions"),
        pytest.param(POLISHED, _shifted, id="relion30"),
        pytest.param(CS, _every_third, id="cs"),
    ],
)
def test_a_streamed_write_never_reads_the_source_whole(
    tmp_path, monkeypatch, source, edit
):
    view = rxm.read(str(source))["particles"]
    write = edit(view)

    with monkeypatch.context() as patched:
        patched.setattr(RawResult, "reread", _refused)
        view.write(str(tmp_path / "out.star"), **write)
    monkeypatch.setattr(ReadResult, "_whole_needed", lambda *_: True)
    view.write(str(tmp_path / "whole.star"), **write)

    streamed = (tmp_path / "out.star").read_text()
    assert streamed == (tmp_path / "whole.star").read_text()


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
    out = str(tmp_path / "out.star")
    view = rxm.read(str(SUBTOMO))["particles"]

    with pytest.raises(ValueError, match=message):
        view.write(out, rows=rows)

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

    writer = StarWriter()
    failing = chunks()

    with pytest.raises(RuntimeError, match="went away"):
        writer.write_chunks(str(out), failing)

    assert not out.exists()
