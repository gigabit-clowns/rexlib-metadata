# SPDX-License-Identifier: LGPL-2.1-or-later

import math
import shutil

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

import rexlib_metadata as rxm
from rexlib_metadata import pose
from rexlib_metadata.abc import Writer
from rexlib_metadata.convention import ConventionBundle, RawTable
from rexlib_metadata.conventions.relion import (
    WriteImageReference,
    relion4_bundle,
)
from rexlib_metadata.formats.star import StarReader, StarWriter
from rexlib_metadata.registry import MetadataRegistry
from rexlib_metadata.result import RawResult
from rexlib_metadata.rewrite import Rewrite

from .support import CS, POLISHED, STAR, SUBTOMO, assert_same, mylab


def _moved(transforms, by):
    along_x = np.eye(1, 12, 3)[0]
    return [transform + by * along_x for transform in transforms]


def _plain(view):
    return view


def _shifted(view):
    frame = view.to_pandas()
    frame["transform"] = _moved(frame["transform"], 1.5)
    return view.updated(frame[["transform"]])


def _every_third(view):
    return view.take(list(range(0, len(view.to_pandas()), 3)))


def _a_mask(view):
    return view.where([n % 2 == 0 for n in range(len(view.to_pandas()))])


def _kept_and_shifted(view):
    frame = view.to_pandas().iloc[::3].copy()
    frame["transform"] = _moved(frame["transform"], -2.0)
    return view.take(frame.index).updated(frame[["transform"]])


def _backwards(view):
    return view.take(list(range(len(view.to_pandas())))[::-1])


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


def _written(view, out, rows_per_chunk):
    view.write(str(out), chunk_size=rows_per_chunk)
    return out.read_bytes()


@pytest.mark.parametrize(("source", "suffix", "name", "edit"), CASES)
def test_a_file_written_in_chunks_is_the_file_written_whole(
    tmp_path, monkeypatch, source, suffix, name, edit
):
    view = edit(rxm.read(str(source))[name])

    chunked = _written(view, tmp_path / f"c{suffix}", 2)
    monkeypatch.setattr(StarWriter, "write_chunks", Writer.write_chunks)
    monkeypatch.setattr(Rewrite, "_whole_needed", lambda *_: True)
    whole = _written(view, tmp_path / f"w{suffix}", 10**9)

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
    "edit",
    [
        pytest.param(lambda view: view.take([0, 1]), id="first-setting"),
        pytest.param(lambda view: view.take([7, 8]), id="second-setting"),
        pytest.param(
            lambda view: view.where([n < 5 for n in range(10)]), id="mask"
        ),
    ],
)
def test_relion30_with_two_settings_writes_in_chunks_as_whole(
    tmp_path, monkeypatch, edit
):
    view = edit(rxm.read(str(_two_settings(tmp_path)))["particles"])

    chunked = _written(view, tmp_path / "c.star", 2)
    monkeypatch.setattr(StarWriter, "write_chunks", Writer.write_chunks)
    monkeypatch.setattr(Rewrite, "_whole_needed", lambda *_: True)
    whole = _written(view, tmp_path / "w.star", 10**9)

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
    view = edit(rxm.read(str(source))["particles"])

    with monkeypatch.context() as patched:
        patched.setattr(RawResult, "_reread", _refused)
        view.write(str(tmp_path / "out.star"))
    monkeypatch.setattr(Rewrite, "_whole_needed", lambda *_: True)
    view.write(str(tmp_path / "whole.star"))

    streamed = (tmp_path / "out.star").read_text()
    assert streamed == (tmp_path / "whole.star").read_text()


def _refused(_):
    raise AssertionError("the source was read whole")


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        pytest.param(
            lambda view: view.where([True, False]),
            "mask holds 2 booleans where table",
            id="mask",
        ),
        pytest.param(
            lambda view: view.take([0, 57]),
            "outside table 'particles'",
            id="outside",
        ),
    ],
)
def test_rows_that_do_not_fit_a_streamed_table_leave_no_file(
    tmp_path, edit, message
):
    out = str(tmp_path / "out.star")
    view = edit(rxm.read(str(SUBTOMO))["particles"])

    with pytest.raises(ValueError, match=message):
        view.write(out)

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


def test_a_write_reads_its_source_chunk_size_rows_at_a_time(
    tmp_path, monkeypatch
):
    sizes = []
    chunks = RawResult._chunks

    def counted(raw, size, columns=None):
        sizes.append(size)
        return chunks(raw, size, columns)

    monkeypatch.setattr(RawResult, "_chunks", counted)
    rxm.read(str(SUBTOMO))["particles"].write(
        str(tmp_path / "out.star"), chunk_size=7
    )

    assert 7 in sizes


@pytest.mark.parametrize("size", [0, -1], ids=["zero", "negative"])
def test_a_write_of_chunks_of_no_rows_is_refused(tmp_path, size):
    out = tmp_path / "out.star"
    source = rxm.read(str(SUBTOMO))

    with pytest.raises(ValueError, match="at least one row"):
        source.write(str(out), chunk_size=size)
    assert not out.exists()


PSI_ONLY = """data_particles

loop_
_rlnImageName
_rlnAnglePsi
_rlnOriginXAngst
_rlnOriginYAngst
000001@a.mrcs 10.0 1.0 2.0
000002@a.mrcs 20.0 3.0 4.0
"""


def _frames(result):
    return {name: result[name].to_pandas() for name in result.names}


def _psi_only(tmp_path):
    path = tmp_path / "psi.star"
    path.write_text(PSI_ONLY)
    return str(path)


def test_blocks_no_convention_fills_reach_a_file_of_the_same_format(tmp_path):
    out = tmp_path / "out.star"
    source = rxm.read(str(STAR / "postprocess.star"))

    source.write(str(out))
    again = rxm.read(str(out)).raw

    assert again.names == ("general", "fsc", "guinier")
    for name, frame in _frames(source.raw).items():
        assert again[name].to_pandas().equals(frame)


def test_a_file_written_over_itself_keeps_every_block(tmp_path):
    path = tmp_path / "postprocess.star"
    shutil.copy(STAR / "postprocess.star", path)

    rxm.read(str(path)).write(str(path))

    assert rxm.read(str(path)).raw.names == ("general", "fsc", "guinier")


def test_a_second_block_of_particles_is_not_lost(tmp_path):
    out = tmp_path / "out.star"

    rxm.read(str(STAR / "rln3.1_data_style.star")).write(str(out))

    assert "block_3" in rxm.read(str(out)).raw.names


def test_a_write_that_would_hold_nothing_raises_and_leaves_the_file(tmp_path):
    out = tmp_path / "out.xmd"
    out.write_text("kept")
    source = rxm.read(str(STAR / "postprocess.star"))

    with pytest.raises(ValueError, match="Nothing of"):
        source.write(str(out))
    assert out.read_text() == "kept"


def _turned(psi):
    zero = np.zeros(len(psi))
    a = pose.euler_matrix(zero, zero, np.array(psi))
    return pa.table({"transform": pose.transforms(a, (zero, zero, zero))})


def test_an_in_plane_angle_reads_on_its_own(tmp_path):
    df = rxm.read(_psi_only(tmp_path))["particles"].to_pandas()

    rot, tilt, psi = pose.euler(df["transform"])

    assert psi.tolist() == pytest.approx([10.0, 20.0])
    assert rot.tolist() == tilt.tolist() == [0.0, 0.0]


def test_an_update_to_a_pose_reaches_the_file(tmp_path):
    out = tmp_path / "out.star"
    particles = rxm.read(_psi_only(tmp_path))["particles"]

    particles.updated(_turned([99.0, 98.0])).write(str(out))

    again = rxm.read(str(out)).raw["particles"].to_pandas()
    assert again["_rlnAnglePsi"].tolist() == ["99", "98"]
    assert again["_rlnOriginXAngst"].tolist() == ["0", "0"]


def test_an_update_no_convention_writes_raises(tmp_path):
    images = ConventionBundle(
        "images", write={"particles": [WriteImageReference()]}
    )
    particles = rxm.read(_psi_only(tmp_path))["particles"]
    out = str(tmp_path / "out.star")
    edited = particles.updated(_turned([99.0, 98.0]))

    with pytest.raises(ValueError, match="'transform'"):
        edited.write(out, bundle=images)


def test_two_extensions_of_one_writer_are_one_format(tmp_path):
    source = tmp_path / "s.sqlite"
    rxm.read(str(STAR / "relion3.1_subtomo.star")).raw.write(str(source))
    relion = relion4_bundle()

    rxm.read(str(source), bundle=relion).write(
        str(tmp_path / "t.db"), bundle=relion
    )

    again = rxm.read(str(tmp_path / "t.db")).raw["particles"].to_pandas()
    before = rxm.read(str(source)).raw["particles"].to_pandas()
    assert set(again.columns) == set(before.columns)


def test_a_writer_named_as_the_registered_one_is_the_same_format(tmp_path):
    out = tmp_path / "out.star"

    rxm.read(str(STAR / "one_loop.star")).write(str(out), writer=StarWriter())

    assert "_rlnCtfImage" in rxm.read(str(out)).raw.to_pandas().columns


def test_a_missing_number_survives_a_round_trip(tmp_path):
    out = tmp_path / "out.star"
    particles = rxm.read(str(STAR / "relion3.1_subtomo.star"))["particles"]
    updates = particles.to_pandas()[["coord_x"]]
    updates.loc[0, "coord_x"] = math.nan

    particles.updated(updates).write(str(out))

    again = rxm.read(str(out))["particles"].to_pandas()
    assert math.isnan(again["coord_x"][0])
    assert again["coord_x"][1] == updates["coord_x"][1]


def test_an_empty_angle_in_a_file_is_no_turn(tmp_path):
    path = tmp_path / "empty.star"
    path.write_text(PSI_ONLY.replace("10.0 1.0", '"" 1.0'))

    df = rxm.read(str(path))["particles"].to_pandas()

    _, _, psi = pose.euler(df["transform"])
    assert psi.tolist() == pytest.approx([0.0, 20.0])


def test_a_null_pose_is_written_empty(tmp_path):
    out = tmp_path / "out.star"
    particles = rxm.read(_psi_only(tmp_path))["particles"]
    updates = _turned([99.0, 98.0])
    nulled = pa.array([None, updates.column(0)[1].as_py()], pose.TRANSFORM)

    particles.updated(pa.table({"transform": nulled})).write(str(out))

    again = rxm.read(str(out)).raw["particles"].to_pandas()
    assert again["_rlnAnglePsi"].tolist() == ["", "98"]


@pytest.mark.parametrize(
    ("suffix", "carry", "kept"),
    [
        pytest.param(".star", None, True, id="same-format"),
        pytest.param(".star", False, False, id="left-out"),
        pytest.param(".xmd", None, False, id="other-format"),
        pytest.param(".xmd", True, True, id="carried-over"),
    ],
)
def test_carry_says_whether_what_no_convention_covers_reaches_the_file(
    tmp_path, suffix, carry, kept
):
    out = tmp_path / f"out{suffix}"
    source = rxm.read(str(STAR / "relion3.1_subtomo.star"))
    before = source.raw["particles"].to_pandas()["_rlnCtfImage"]

    source.write(str(out), carry=carry)

    written = rxm.read(str(out)).raw["particles"].to_pandas()
    assert ("_rlnCtfImage" in written.columns) is kept
    if kept:
        assert written["_rlnCtfImage"].tolist() == before.tolist()


def test_blocks_no_convention_fills_are_left_out_with_carry_false(tmp_path):
    out = tmp_path / "out.star"
    source = rxm.read(str(STAR / "postprocess.star"))

    with pytest.raises(ValueError, match="Nothing of"):
        source.write(str(out), carry=False)
    assert not out.exists()


class _Recorder(Writer):
    def __init__(self) -> None:
        self.tables: list[RawTable] = []

    def write_tables(self, path, tables):
        self.tables = list(tables)


def _rewritten(name, tmp_path):
    source = rxm.read(str(STAR / name))
    out = tmp_path / "out.star"
    source.write(str(out))
    return source, rxm.read(str(out))


def test_a_canonical_table_writes_back_the_same(tmp_path):
    source, again = _rewritten("one_loop.star", tmp_path)

    pd.testing.assert_frame_equal(
        source["particles"].to_pandas(), again["particles"].to_pandas()
    )


def test_every_canonical_table_becomes_its_own_block(tmp_path):
    source, again = _rewritten("rln3.1_data_style.star", tmp_path)

    assert again.names == ("particles", "optics")
    assert again.raw.names == ("optics", "particles", "block_3")
    for name in source.names:
        pd.testing.assert_frame_equal(
            source[name].to_pandas(), again[name].to_pandas()
        )


def test_a_pose_is_written_as_relion_spells_it(tmp_path):
    source = rxm.read(str(STAR / "relion3.1_subtomo.star"))
    particles = source["particles"]
    before = source.raw["particles"].to_pandas()
    a, origin = pose.relion(particles.to_pandas()["transform"])
    moved = pose.transforms(a, (origin[0] + 1.5, origin[1], origin[2]))
    out = tmp_path / "out.star"

    particles.updated(pa.table({"transform": moved})).write(str(out))
    raw = rxm.read(str(out)).raw["particles"].to_pandas()

    assert float(raw["_rlnOriginXAngst"][0]) == pytest.approx(
        float(before["_rlnOriginXAngst"][0]) + 1.5, abs=1e-5
    )
    assert float(raw["_rlnOriginZAngst"][1]) == pytest.approx(
        float(before["_rlnOriginZAngst"][1]), abs=1e-5
    )
    assert float(raw["_rlnAngleTilt"][0]) == pytest.approx(
        float(before["_rlnAngleTilt"][0]), abs=1e-4
    )


def test_a_column_no_convention_writes_is_carried_over(tmp_path):
    source, again = _rewritten("one_loop.star", tmp_path)

    before = set(source.raw.to_pandas().columns)
    after = set(again.raw.to_pandas().columns)

    assert {"_rlnCtfImage", "_rlnMagnification"} <= before
    assert before <= after


def test_a_reference_that_had_an_index_comes_back_as_it_was(tmp_path):
    source, again = _rewritten("rln3.1_data_style.star", tmp_path)

    assert (
        again.raw["particles"].to_pandas()["_rlnImageName"].tolist()
        == source.raw["block_2"].to_pandas()["_rlnImageName"].tolist()
    )


def test_a_bare_path_comes_back_carrying_the_first_index(tmp_path):
    _, again = _rewritten("one_loop.star", tmp_path)

    names = again.raw.to_pandas()["_rlnImageName"]

    assert names[0] == "000001@" + names[0].split("@")[1]
    assert names[0].endswith("tomo_ts01.mrc_0000000_5.00A.mrc")


def test_a_number_is_written_as_short_as_it_can_be(tmp_path):
    _, again = _rewritten("rln3.1_data_style.star", tmp_path)

    particles = again.raw["particles"].to_pandas()
    optics = again.raw["optics"].to_pandas()

    assert particles["_rlnCoordinateX"].tolist() == ["587", "685"]
    assert optics["_rlnSphericalAberration"][0] == "2.7"


def test_a_bundle_of_your_own_writes_instead(tmp_path):
    source = rxm.read(str(STAR / "one_loop.star"))
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

    registry.read(str(STAR / "one_loop.star")).write(str(tmp_path / "o.xmd"))

    columns = recorder.tables[0].table.column_names
    assert "_rlnCoordinateX" in columns
    assert "_rlnCtfImage" not in columns


def test_a_table_no_convention_writes_says_so(tmp_path):
    source = rxm.read(str(STAR / "one_loop.star"))

    nothing = ConventionBundle("none")

    with pytest.raises(ValueError, match="writes canonical table"):
        source.write(str(tmp_path / "out.star"), bundle=nothing)


def test_a_write_takes_several_bundles_too(tmp_path):
    out = tmp_path / "out.star"
    source = rxm.read(str(SUBTOMO))

    source.write(str(out), bundle=[mylab(), relion4_bundle()])

    assert_same(
        rxm.read(str(out))["particles"].to_pandas(),
        source["particles"].to_pandas(),
    )


def test_a_joined_view_writes_its_own_columns_back(tmp_path):
    out = tmp_path / "out.star"
    source = rxm.read(str(SUBTOMO))
    view = source.joined("particles")
    flat = view.to_pandas()
    flat["coord_x"] += 1.0

    view.updated(flat).write(str(out))

    again = rxm.read(str(out))
    moved = again["particles"].to_pandas()["coord_x"].tolist()
    assert moved == pytest.approx(flat["coord_x"].tolist())
    assert_same(again["optics"].to_pandas(), source["optics"].to_pandas())


def test_a_joined_view_refuses_a_change_to_the_table_it_points_at(tmp_path):
    view = rxm.read(str(SUBTOMO)).joined("particles")
    flat = view.to_pandas()
    flat["pixel_size"] = 6.0
    out = str(tmp_path / "out.star")
    edited = view.updated(flat)

    with pytest.raises(ValueError, match="'pixel_size'"):
        edited.write(out)
