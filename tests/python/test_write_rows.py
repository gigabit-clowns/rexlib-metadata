# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path

import pandas as pd
import polars as pl
import pytest

import rexlib_metadata as rxm

FILES = Path(__file__).parent.parent / "files" / "star"
FILE = FILES / "relion3.1_subtomo.star"


def particles():
    return rxm.read(str(FILE))["particles"]


def written(tmp_path, suffix=".star", **write):
    out = tmp_path / f"out{suffix}"
    particles().write(str(out), **write)
    return rxm.read(str(out))


def test_rows_by_position_keep_those_rows_in_that_order(tmp_path):
    source = particles().to_pandas()

    again = written(tmp_path, rows=[10, 0, 5])["particles"].to_pandas()

    pd.testing.assert_frame_equal(
        again, source.iloc[[10, 0, 5]].reset_index(drop=True)
    )


def test_a_filtered_frame_hands_its_index_over(tmp_path):
    source = particles().to_pandas()
    kept = source[source["shift_x"] > 0]

    again = written(tmp_path, rows=kept.index)["particles"].to_pandas()

    pd.testing.assert_frame_equal(again, kept.reset_index(drop=True))


def test_a_mask_keeps_the_rows_it_marks(tmp_path):
    source = particles().to_pandas()
    mask = (source["shift_x"] > 0).to_numpy()

    again = written(tmp_path, rows=mask)["particles"].to_pandas()

    assert len(again) == mask.sum()


def test_the_columns_no_convention_writes_follow_the_rows(tmp_path):
    raw = rxm.read(str(FILE)).raw["particles"].to_pandas()

    again = written(tmp_path, rows=[3, 1]).raw

    assert again["particles"].to_pandas()["_rlnCtfImage"].tolist() == (
        raw["_rlnCtfImage"].iloc[[3, 1]].tolist()
    )


def test_the_other_tables_are_written_whole(tmp_path):
    again = written(tmp_path, rows=[0])

    assert len(again["optics"].to_pandas()) == 1
    assert len(again["particles"].to_pandas()) == 1


def test_updates_hold_one_row_per_row_kept(tmp_path):
    source = particles().to_pandas()
    kept = source.iloc[[2, 4]].copy()
    kept["shift_x"] += 1.5

    again = written(tmp_path, rows=kept.index, updates=kept[["shift_x"]])

    assert again["particles"].to_pandas()["shift_x"].tolist() == pytest.approx(
        (source["shift_x"].iloc[[2, 4]] + 1.5).tolist()
    )


def test_updates_of_another_length_say_what_they_should_hold(tmp_path):
    source = particles().to_pandas()
    view = particles()
    out = str(tmp_path / "out.star")
    updates = source[["shift_x"]]

    with pytest.raises(ValueError, match="one per row rows= keeps"):
        view.write(out, rows=[0, 1], updates=updates)


def test_rows_may_come_from_polars(tmp_path):
    again = written(tmp_path, rows=pl.Series([1, 2]))

    assert len(again["particles"].to_pandas()) == 2


def test_rows_reach_a_format_with_no_optics_table(tmp_path):
    again = written(tmp_path, suffix=".xmd", rows=[0, 1, 2])

    assert len(again["particles"].to_pandas()) == 3


@pytest.mark.parametrize(
    ("rows", "error", "message"),
    [
        ([True, False], ValueError, "mask of 2 where table 'particles'"),
        ([0, 57], ValueError, "outside table 'particles'"),
        ([-1], ValueError, "outside table 'particles'"),
        ([0.5], TypeError, "positions or a mask"),
    ],
)
def test_rows_that_name_no_row_are_refused(tmp_path, rows, error, message):
    view = particles()
    out = str(tmp_path / "out.star")

    with pytest.raises(error, match=message):
        view.write(out, rows=rows)


def test_rows_of_a_result_of_several_tables_ask_which(tmp_path):
    result = rxm.read(str(FILE))
    out = str(tmp_path / "out.star")

    with pytest.raises(ValueError, match="name the one you mean"):
        result.write(out, rows=[0])
