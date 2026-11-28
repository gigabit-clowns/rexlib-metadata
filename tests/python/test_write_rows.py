# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import pandas as pd
import polars as pl
import pytest

import rexlib_metadata as rxm

from .frames import assert_same

FILES = Path(__file__).parent.parent / "files" / "star"
FILE = FILES / "relion3.1_subtomo.star"


def particles():
    return rxm.read(str(FILE))["particles"]


def written(tmp_path, view, suffix=".star"):
    out = tmp_path / f"out{suffix}"
    view.write(str(out))
    return rxm.read(str(out))


def test_rows_by_position_keep_those_rows_in_that_order(tmp_path):
    source = particles().to_pandas()

    again = written(tmp_path, particles().take([10, 0, 5]))

    expected = source.iloc[[10, 0, 5]].reset_index(drop=True)
    assert_same(again["particles"].to_pandas(), expected)


def test_a_filtered_frame_hands_its_index_over(tmp_path):
    source = particles().to_pandas()
    kept = source[source["coord_x"] > source["coord_x"].median()]

    again = written(tmp_path, particles().take(kept.index))

    assert_same(again["particles"].to_pandas(), kept.reset_index(drop=True))


def test_a_mask_keeps_the_rows_it_marks(tmp_path):
    source = particles().to_pandas()
    mask = (source["coord_x"] > source["coord_x"].median()).to_numpy()

    again = written(tmp_path, particles().where(mask))

    expected = source[mask].reset_index(drop=True)
    assert_same(again["particles"].to_pandas(), expected)


def test_the_columns_no_convention_writes_follow_the_rows(tmp_path):
    raw = rxm.read(str(FILE)).raw["particles"].to_pandas()

    again = written(tmp_path, particles().take([3, 1])).raw

    assert again["particles"].to_pandas()["_rlnCtfImage"].tolist() == (
        raw["_rlnCtfImage"].iloc[[3, 1]].tolist()
    )


def test_the_other_tables_are_written_whole(tmp_path):
    source = rxm.read(str(FILE))["optics"].to_pandas()

    again = written(tmp_path, particles().take([0]))

    assert_same(again["optics"].to_pandas(), source)
    assert len(again["particles"].to_pandas()) == 1


def test_updates_hold_one_row_per_row_kept(tmp_path):
    source = particles().to_pandas()
    kept = source.iloc[[2, 4]].copy()
    kept["coord_x"] += 1.5

    view = particles().take(kept.index).updated(kept[["coord_x"]])
    again = written(tmp_path, view)

    assert again["particles"].to_pandas()["coord_x"].tolist() == pytest.approx(
        (source["coord_x"].iloc[[2, 4]] + 1.5).tolist()
    )


def test_updates_of_another_length_say_what_they_should_hold(tmp_path):
    source = particles().to_pandas()
    view = particles().take([0, 1]).updated(source[["coord_x"]])
    out = str(tmp_path / "out.star")

    with pytest.raises(ValueError, match="one per row kept"):
        view.write(out)
    with pytest.raises(ValueError, match="one per row kept"):
        view.to_pandas()


def test_rows_may_come_from_polars(tmp_path):
    again = written(tmp_path, particles().take(pl.Series([1, 2])))

    assert len(again["particles"].to_pandas()) == 2


def test_rows_reach_a_format_with_no_optics_table(tmp_path):
    source = particles().to_pandas()

    again = written(tmp_path, particles().take([0, 1, 2]), suffix=".xmd")

    reference = ["image_path", "image_index"]
    assert_same(
        again["particles"].to_pandas()[reference],
        source[reference].iloc[[0, 1, 2]].reset_index(drop=True),
    )


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        pytest.param(
            lambda view: view.where([True, False]),
            "mask holds 2 booleans where table 'particles'",
            id="short-mask",
        ),
        pytest.param(
            lambda view: view.take([0, 57]),
            "outside table 'particles'",
            id="past-the-end",
        ),
        pytest.param(
            lambda view: view.take([-1]),
            "outside table 'particles'",
            id="negative",
        ),
    ],
)
def test_rows_that_name_no_row_are_refused(tmp_path, edit, message):
    view = edit(particles())
    out = str(tmp_path / "out.star")

    with pytest.raises(ValueError, match=message):
        view.write(out)
    with pytest.raises(ValueError, match=message):
        view.to_pandas()


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        pytest.param(
            lambda view: view.take([0.5]), "row positions", id="floats"
        ),
        pytest.param(
            lambda view: view.where([0, 1]), "a boolean per row", id="ints"
        ),
    ],
)
def test_rows_of_the_wrong_kind_are_refused_at_once(edit, message):
    with pytest.raises(TypeError, match=message):
        edit(particles())


@pytest.mark.parametrize(
    "edit",
    [
        pytest.param(lambda view: view.take([0]).take([0]), id="twice"),
        pytest.param(
            lambda view: view.updated(pd.DataFrame()).take([0]),
            id="after-updates",
        ),
        pytest.param(
            lambda view: view.updated(pd.DataFrame()).updated(
                pd.DataFrame()
            ),
            id="updated-twice",
        ),
    ],
)
def test_a_view_is_edited_once_rows_first(edit):
    with pytest.raises(ValueError, match="once"):
        edit(particles())


def test_rows_of_a_result_of_several_tables_ask_which(tmp_path):
    view = rxm.read(str(FILE)).take([0])
    out = str(tmp_path / "out.star")

    with pytest.raises(ValueError, match="name the one you mean"):
        view.write(out)


def test_no_rows_write_the_table_empty(tmp_path):
    source = rxm.read(str(FILE))["optics"].to_pandas()

    again = written(tmp_path, particles().take([]))

    assert len(again["particles"].to_pandas()) == 0
    assert_same(again["optics"].to_pandas(), source)


@pytest.mark.parametrize(
    "edit",
    [
        pytest.param(lambda view, _: view.take([10, 0, 5]), id="positions"),
        pytest.param(
            lambda view, frame: view.where(frame["coord_x"] > 0), id="mask"
        ),
        pytest.param(
            lambda view, frame: view.take([3, 1]).updated(
                frame[["coord_x"]].iloc[[3, 1]] + 1.0
            ),
            id="kept-and-updated",
        ),
    ],
)
def test_an_edited_view_reads_as_it_writes(tmp_path, edit):
    view = edit(particles(), particles().to_pandas())

    read = view.to_pandas()
    chunked = pd.concat(
        [chunk.to_pandas() for chunk in view.chunks(2)], ignore_index=True
    )
    again = written(tmp_path, view)["particles"].to_pandas()

    assert_same(chunked, read)
    assert_same(again, read)


def test_an_updated_joined_view_may_not_change_what_it_points_at():
    view = rxm.read(str(FILE)).joined("particles")
    frame = view.to_pandas()
    frame["voltage"] = 100.0

    with pytest.raises(ValueError, match="'voltage', which table 'particles'"):
        view.updated(frame).to_pandas()
